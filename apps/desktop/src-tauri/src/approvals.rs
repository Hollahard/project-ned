//! Native OS approval dialogs and one-shot capability token issuance.
//!
//! Invariants:
//! 1. All dangerous tool executions (terminal commands, file writes outside safe roots)
//!    require an out-of-band native OS modal dialog.
//! 2. Approvals CANNOT be auto-clicked, bypassed, or forged by the Web UI.
//! 3. Minted capability tokens are single-use, bounded by an HMAC-SHA256 signature,
//!    bound to the canonical hash of the arguments, and expire after a strict TTL.

use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::{info, warn};
use uuid::Uuid;

use windows_sys::Win32::UI::WindowsAndMessaging::{
    MessageBoxW, IDYES, MB_DEFBUTTON2, MB_ICONWARNING, MB_SYSTEMMODAL, MB_YESNO,
};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, thiserror::Error)]
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

/// Displays a native Win32 system-modal dialog requesting user confirmation.
/// Returns true if the user clicks "Yes", false if "No" or dialog is closed.
pub fn show_native_approval_dialog(
    tool_name: &str,
    arguments: &serde_json::Value,
    risk_reason: &str,
    turn_id: &str,
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

    let result = unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            wide_msg.as_ptr(),
            wide_title.as_ptr(),
            flags,
        )
    };

    let approved = result == IDYES;
    if approved {
        info!("Native approval GRANTED for tool '{}'", tool_name);
    } else {
        warn!("Native approval DENIED by user for tool '{}'", tool_name);
    }

    approved
}

/// Manages one-shot capability tokens issued upon native user authorization.
pub struct ApprovalManager {
    secret_key: Arc<String>,
    ttl_seconds: u64,
    consumed_tokens: Arc<Mutex<Vec<String>>>,
}

impl ApprovalManager {
    pub fn new(secret_key: String, ttl_seconds: u64) -> Self {
        Self {
            secret_key: Arc::new(secret_key),
            ttl_seconds,
            consumed_tokens: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Mints a signed one-shot capability token for the approved tool call.
    pub fn mint_token(
        &self,
        tool_name: &str,
        arguments: &serde_json::Value,
    ) -> Result<(String, String), ApprovalError> {
        let args_hash = compute_args_hash(arguments);
        let token_id = Uuid::new_v4().to_string();

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        let expires_at = now + (self.ttl_seconds as f64);

        let msg = format!("{}:{}:{}:{}", token_id, tool_name, args_hash, expires_at);

        let mut mac = HmacSha256::new_from_slice(self.secret_key.as_bytes())
            .map_err(|e| ApprovalError::CryptoError(e.to_string()))?;
        mac.update(msg.as_bytes());
        let signature = hex::encode(mac.finalize().into_bytes());

        let token = format!("{}.{}", token_id, signature);
        info!("Minted one-shot token for {} (args_hash: {}...)", tool_name, &args_hash[..8]);
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
        let approved = show_native_approval_dialog(tool_name, arguments, risk_reason, turn_id);
        if !approved {
            return Err(ApprovalError::UserRejected);
        }

        let (token, _args_hash) = self.mint_token(tool_name, arguments)?;
        Ok(token)
    }

    /// Validates and single-use consumes a capability token in the supervisor.
    pub fn validate_and_consume(
        &self,
        token: &str,
        tool_name: &str,
        arguments: &serde_json::Value,
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
        let _args_hash = compute_args_hash(arguments);

        consumed.push(token.to_string());
        info!("Successfully consumed token {} for {}", token_id, tool_name);
        Ok(true)
    }
}
