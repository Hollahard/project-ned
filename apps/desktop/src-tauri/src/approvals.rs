//! Native OS approval dialogs and one-shot capability token issuance.
//!
//! Invariants:
//! 1. All dangerous tool executions (terminal commands, file writes outside safe roots)
//!    require an out-of-band native OS modal dialog.
//! 2. Approvals CANNOT be auto-clicked, bypassed, or forged by the Web UI.
//! 3. Minted capability tokens are single-use, bounded by an HMAC-SHA256 signature,
//!    bound to the canonical hash of the arguments, bound to caller Win32 HWND, and expire after a strict TTL.

use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::{info, warn};
use uuid::Uuid;

use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, MessageBoxW, IDYES, MB_DEFBUTTON2, MB_ICONWARNING,
    MB_SYSTEMMODAL, MB_YESNO,
};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ApprovalError {
    #[error("User rejected the approval request in native OS modal")]
    UserRejected,
    #[error("Failed to compute HMAC signature: {0}")]
    CryptoError(String),
    #[error("Invalid token format")]
    InvalidTokenFormat,
    #[error("Token expired")]
    TokenExpired,
    #[error("Token already consumed")]
    TokenAlreadyConsumed,
    #[error("Argument hash mismatch")]
    ArgHashMismatch,
}

/// Recursively canonicalize serde_json::Value to produce identical output to
/// Python's json.dumps(sort_keys=True, separators=(',', ':')).
pub fn canonicalize_json_value(val: &serde_json::Value) -> serde_json::Value {
    match val {
        serde_json::Value::Object(map) => {
            let mut sorted = BTreeMap::new();
            for (k, v) in map {
                sorted.insert(k.clone(), canonicalize_json_value(v));
            }
            serde_json::to_value(sorted).unwrap()
        }
        serde_json::Value::Array(arr) => {
            let sorted: Vec<serde_json::Value> = arr.iter().map(canonicalize_json_value).collect();
            serde_json::Value::Array(sorted)
        }
        _ => val.clone(),
    }
}

/// Compute SHA-256 hash of canonical JSON-serialized arguments.
pub fn compute_args_hash(arguments: &serde_json::Value) -> String {
    let canonical = canonicalize_json_value(arguments);
    let serialized = serde_json::to_string(&canonical).unwrap_or_else(|_| "{}".to_string());
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    hex::encode(hasher.finalize())
}

/// Resolves the caller's active foreground Win32 window handle (HWND).
/// Returns null_mut() if foreground window cannot be determined.
pub fn resolve_caller_hwnd() -> HWND {
    unsafe {
        let foreground = GetForegroundWindow();
        if !foreground.is_null() {
            return foreground;
        }
        std::ptr::null_mut()
    }
}

/// Displays a native Win32 system-modal dialog requesting user confirmation,
/// explicitly bound to the caller's Win32 HWND.
/// Returns true if the user clicks "Yes", false if "No" or dialog is closed.
pub fn show_native_approval_dialog_with_hwnd(
    tool_name: &str,
    arguments: &serde_json::Value,
    risk_reason: &str,
    turn_id: &str,
    hwnd: HWND,
) -> bool {
    let pretty_args = serde_json::to_string_pretty(arguments).unwrap_or_default();
    let message = format!(
        "SECURITY APPROVAL REQUIRED\n\n\
        The agent is requesting permission to execute a high-risk action:\n\n\
        Tool: {}\n\
        Risk: {}\n\
        Turn ID: {}\n\n\
        Arguments:\n{}\n\n\
        Do you explicitly authorize this specific execution?",
        tool_name, risk_reason, turn_id, pretty_args
    );

    let title = "Project Friday - Security Authorization";

    let wide_msg: Vec<u16> = OsStr::new(&message).encode_wide().chain(Some(0)).collect();
    let wide_title: Vec<u16> = OsStr::new(title).encode_wide().chain(Some(0)).collect();

    // MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SYSTEMMODAL
    // Default button is "No" (safe by default). System modal prevents webview overlay.
    let flags = MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SYSTEMMODAL;

    let parent_hwnd = if !hwnd.is_null() {
        hwnd
    } else {
        resolve_caller_hwnd()
    };

    let result = unsafe {
        MessageBoxW(
            parent_hwnd,
            wide_msg.as_ptr(),
            wide_title.as_ptr(),
            flags,
        )
    };

    let approved = result == IDYES;
    if approved {
        info!(
            "Native approval GRANTED for tool '{}' (bound HWND: {:p})",
            tool_name, parent_hwnd
        );
    } else {
        warn!(
            "Native approval DENIED by user for tool '{}' (bound HWND: {:p})",
            tool_name, parent_hwnd
        );
    }

    approved
}

/// Displays a native Win32 system-modal dialog requesting user confirmation,
/// dynamically resolving and binding to the caller's foreground Win32 HWND.
pub fn show_native_approval_dialog(
    tool_name: &str,
    arguments: &serde_json::Value,
    risk_reason: &str,
    turn_id: &str,
) -> bool {
    show_native_approval_dialog_with_hwnd(
        tool_name,
        arguments,
        risk_reason,
        turn_id,
        resolve_caller_hwnd(),
    )
}

/// Metadata record tracking an active, unconsumed capability token.
#[derive(Debug, Clone)]
pub struct ActiveTokenRecord {
    pub tool_name: String,
    pub args_hash: String,
    pub expires_at: f64,
    pub bound_hwnd: Option<isize>,
}

/// Manages one-shot capability tokens issued upon native user authorization.
pub struct ApprovalManager {
    secret_key: Arc<String>,
    ttl_seconds: u64,
    consumed_tokens: Arc<Mutex<Vec<String>>>,
    active_tokens: Arc<Mutex<HashMap<String, ActiveTokenRecord>>>,
    bound_hwnd: Arc<Mutex<Option<isize>>>,
}

impl ApprovalManager {
    pub fn new(secret_key: String, ttl_seconds: u64) -> Self {
        Self {
            secret_key: Arc::new(secret_key),
            ttl_seconds,
            consumed_tokens: Arc::new(Mutex::new(Vec::new())),
            active_tokens: Arc::new(Mutex::new(HashMap::new())),
            bound_hwnd: Arc::new(Mutex::new(None)),
        }
    }

    /// Bind this manager to a caller Win32 HWND.
    pub fn bind_hwnd(&self, hwnd: isize) {
        *self.bound_hwnd.lock().unwrap() = Some(hwnd);
    }

    /// Builder pattern helper to set caller Win32 HWND.
    pub fn with_hwnd(self, hwnd: isize) -> Self {
        *self.bound_hwnd.lock().unwrap() = Some(hwnd);
        self
    }

    /// Get current caller Win32 HWND if set or dynamically resolvable.
    pub fn caller_hwnd(&self) -> Option<isize> {
        let guard = self.bound_hwnd.lock().unwrap();
        if let Some(h) = *guard {
            Some(h)
        } else {
            let resolved = resolve_caller_hwnd();
            if !resolved.is_null() {
                Some(resolved as isize)
            } else {
                None
            }
        }
    }

    /// Mints a signed one-shot capability token for the approved tool call,
    /// bound to the caller's Win32 HWND if available.
    pub fn mint_token(
        &self,
        tool_name: &str,
        arguments: &serde_json::Value,
    ) -> Result<(String, String), ApprovalError> {
        let hwnd = self.caller_hwnd();
        self.mint_token_with_hwnd(tool_name, arguments, hwnd)
    }

    /// Mints a signed one-shot capability token explicitly specifying the target HWND.
    pub fn mint_token_with_hwnd(
        &self,
        tool_name: &str,
        arguments: &serde_json::Value,
        hwnd: Option<isize>,
    ) -> Result<(String, String), ApprovalError> {
        let args_hash = compute_args_hash(arguments);
        let token_id = Uuid::new_v4().to_string();

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        let expires_at = now + (self.ttl_seconds as f64);

        let msg = match hwnd {
            Some(h) => format!("{}:{}:{}:{}:hwnd={}", token_id, tool_name, args_hash, expires_at, h),
            None => format!("{}:{}:{}:{}", token_id, tool_name, args_hash, expires_at),
        };

        let mut mac = HmacSha256::new_from_slice(self.secret_key.as_bytes())
            .map_err(|e| ApprovalError::CryptoError(e.to_string()))?;
        mac.update(msg.as_bytes());
        let signature = hex::encode(mac.finalize().into_bytes());

        let token = format!("{}.{}", token_id, signature);

        let record = ActiveTokenRecord {
            tool_name: tool_name.to_string(),
            args_hash: args_hash.clone(),
            expires_at,
            bound_hwnd: hwnd,
        };

        let mut active = self.active_tokens.lock().unwrap();
        // Prune expired tokens during minting to keep memory bounded
        active.retain(|_, rec| now <= rec.expires_at);
        active.insert(token.clone(), record);

        info!(
            "Minted one-shot token for {} (args_hash: {}..., bound_hwnd: {:?})",
            tool_name,
            &args_hash[..8.min(args_hash.len())],
            hwnd
        );
        Ok((token, args_hash))
    }

    /// Gate that prompts the user natively and mints a token if approved.
    pub fn request_approval_and_mint(
        &self,
        tool_name: &str,
        arguments: &serde_json::Value,
        risk_reason: &str,
        turn_id: &str,
    ) -> Result<String, ApprovalError> {
        let hwnd_opt = self.caller_hwnd();
        let parent_hwnd: HWND = hwnd_opt.map(|h| h as HWND).unwrap_or_else(resolve_caller_hwnd);
        let approved = show_native_approval_dialog_with_hwnd(
            tool_name,
            arguments,
            risk_reason,
            turn_id,
            parent_hwnd,
        );
        if !approved {
            return Err(ApprovalError::UserRejected);
        }

        let (token, _args_hash) = self.mint_token_with_hwnd(tool_name, arguments, hwnd_opt)?;
        Ok(token)
    }

    /// Validates and single-use consumes a capability token in the supervisor.
    pub fn validate_and_consume(
        &self,
        token: &str,
        tool_name: &str,
        arguments: &serde_json::Value,
    ) -> Result<bool, ApprovalError> {
        self.validate_and_consume_with_hwnd(token, tool_name, arguments, self.caller_hwnd())
    }

    /// Validates and single-use consumes a capability token with explicit caller HWND verification.
    pub fn validate_and_consume_with_hwnd(
        &self,
        token: &str,
        tool_name: &str,
        arguments: &serde_json::Value,
        caller_hwnd: Option<isize>,
    ) -> Result<bool, ApprovalError> {
        let mut consumed = self.consumed_tokens.lock().unwrap();
        if consumed.contains(&token.to_string()) {
            return Err(ApprovalError::TokenAlreadyConsumed);
        }

        let parts: Vec<&str> = token.split('.').collect();
        if parts.len() != 2 {
            return Err(ApprovalError::InvalidTokenFormat);
        }

        let token_id = parts[0];
        let signature = parts[1];
        let current_args_hash = compute_args_hash(arguments);

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();

        let mut active = self.active_tokens.lock().unwrap();
        let record = match active.remove(token) {
            Some(r) => r,
            None => return Err(ApprovalError::InvalidTokenFormat),
        };

        if now > record.expires_at {
            return Err(ApprovalError::TokenExpired);
        }
        if record.tool_name != tool_name {
            return Err(ApprovalError::ArgHashMismatch);
        }
        if record.args_hash != current_args_hash {
            return Err(ApprovalError::ArgHashMismatch);
        }

        // Verify HWND binding if token was bound to a caller HWND
        if let Some(bound_h) = record.bound_hwnd {
            if let Some(ch) = caller_hwnd {
                if bound_h != ch {
                    return Err(ApprovalError::CryptoError(format!(
                        "Token HWND binding mismatch: token bound to HWND {:#x}, called from {:#x}",
                        bound_h, ch
                    )));
                }
            }
        }

        // Cryptographic signature verification
        let msg = match record.bound_hwnd {
            Some(h) => format!("{}:{}:{}:{}:hwnd={}", token_id, tool_name, record.args_hash, record.expires_at, h),
            None => format!("{}:{}:{}:{}", token_id, tool_name, record.args_hash, record.expires_at),
        };
        let mut mac = HmacSha256::new_from_slice(self.secret_key.as_bytes())
            .map_err(|e| ApprovalError::CryptoError(e.to_string()))?;
        mac.update(msg.as_bytes());
        let expected_sig = hex::encode(mac.finalize().into_bytes());
        if signature != expected_sig {
            return Err(ApprovalError::CryptoError("HMAC signature verification failed".to_string()));
        }

        consumed.push(token.to_string());
        info!("Successfully consumed token {} for {}", token_id, tool_name);
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_canonicalize_json_value_sort_keys_parity() {
        let v1 = serde_json::json!({
            "zebra": 1,
            "apple": 2,
            "nested": {
                "charlie": "c",
                "bravo": "b"
            }
        });
        let v2 = serde_json::json!({
            "nested": {
                "bravo": "b",
                "charlie": "c"
            },
            "apple": 2,
            "zebra": 1
        });

        assert_eq!(compute_args_hash(&v1), compute_args_hash(&v2));
    }

    #[test]
    fn test_token_hwnd_binding_validation() {
        let manager = ApprovalManager::new("secret-test-key".to_string(), 120);
        let args = serde_json::json!({ "cmd": "echo test" });

        // Mint with explicit HWND
        let hwnd_main: isize = 0x1234;
        let (token, _hash) = manager
            .mint_token_with_hwnd("terminal.exec", &args, Some(hwnd_main))
            .expect("Minting should succeed");

        // Validate with matching HWND succeeds
        let res = manager.validate_and_consume_with_hwnd(
            &token,
            "terminal.exec",
            &args,
            Some(hwnd_main),
        );
        assert!(res.is_ok(), "Validation with matching HWND must succeed");

        // Single-use replay fails
        let replay = manager.validate_and_consume_with_hwnd(
            &token,
            "terminal.exec",
            &args,
            Some(hwnd_main),
        );
        assert_eq!(replay, Err(ApprovalError::TokenAlreadyConsumed));

        // Mint another token with HWND
        let (token2, _hash) = manager
            .mint_token_with_hwnd("terminal.exec", &args, Some(hwnd_main))
            .expect("Minting should succeed");

        // Validate with mismatched HWND fails
        let hwnd_alien: isize = 0x5678;
        let mismatch = manager.validate_and_consume_with_hwnd(
            &token2,
            "terminal.exec",
            &args,
            Some(hwnd_alien),
        );
        assert!(mismatch.is_err(), "Validation with mismatched HWND must fail");
    }

    #[test]
    fn test_token_tampered_args_rejected() {
        let manager = ApprovalManager::new("secret-test-key".to_string(), 120);
        let args = serde_json::json!({ "file": "safe.txt" });
        let tampered = serde_json::json!({ "file": "evil.txt" });

        let (token, _) = manager.mint_token("fs.write", &args).unwrap();
        let res = manager.validate_and_consume(&token, "fs.write", &tampered);
        assert_eq!(res, Err(ApprovalError::ArgHashMismatch));
    }

    #[test]
    fn test_token_expired_ttl_rejected() {
        let manager = ApprovalManager::new("secret-test-key".to_string(), 0);
        let args = serde_json::json!({ "tool": "test" });

        let (token, _) = manager.mint_token("test.tool", &args).unwrap();
        // Give time for clock tick
        std::thread::sleep(std::time::Duration::from_millis(10));
        let res = manager.validate_and_consume(&token, "test.tool", &args);
        assert_eq!(res, Err(ApprovalError::TokenExpired));
    }
}

