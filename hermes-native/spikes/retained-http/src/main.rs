#![cfg(windows)]
mod config;

use config::{Prepared, ProofResult};
use hermes_owned_http::{Limits, Method, OwnedHttpClient};
use hermes_resource_host::{CaptureLimits, CapturedWorker, WorkerGroup, WorkerSpec};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::windows::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf, Prefix};
use std::time::{Duration, Instant};
use windows_sys::Win32::Security::Cryptography::{
    BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
};
use windows_sys::Win32::System::SystemInformation::GetWindowsDirectoryW;

const HEADER: &str = "X-Hermes-Session-Token";
type RejectionCase<'a> = (
    Method,
    &'a str,
    Vec<(&'a str, &'a str)>,
    Option<&'a [u8]>,
    u16,
    &'static str,
);

fn main() {
    if let Err(code) = run() {
        // All failure codes are static. Never print arguments, paths, responses,
        // environment values, raw child output or an HTTP transport payload.
        eprintln!("retained HTTP proof failed: {code}");
        std::process::exit(1);
    }
    println!("retained HTTP diagnostic verified; gateway remains unavailable");
}

fn run() -> ProofResult<()> {
    let args: Vec<OsString> = std::env::args_os().collect();
    let fail_after_ready = args.len() == 4 && args[3] == "--fixture-fail-after-ready";
    if (args.len() != 3 && !fail_after_ready) || args[1] != "--config" {
        return Err("ARGUMENTS_INVALID");
    }
    let prepared = Prepared::load(Path::new(&args[2]))?;
    let executable = std::env::current_exe().map_err(|_| "EXECUTABLE_IDENTITY_FAILED")?;
    let executable_hash = config::digest(&config::read_bounded(&executable, 64 * 1024 * 1024)?);
    let start = Instant::now();
    std::fs::create_dir(&prepared.state).map_err(|_| "STATE_CREATE_FAILED")?;
    let child_state = synthetic_state_path(&prepared.state)?;
    let token = fresh_token()?;
    let wrong_token = fresh_token()?;
    let environment = environment(&child_state, &token)?;
    let spec = WorkerSpec {
        executable: prepared.python.clone(),
        arguments: vec![
            "-I".into(),
            "-S".into(),
            "-B".into(),
            "-X".into(),
            "utf8".into(),
            prepared
                .backend_root
                .join("diagnostics/bootstrap.py")
                .into_os_string(),
            "--candidate".into(),
            prepared.candidate.clone().into_os_string(),
            "--state".into(),
            child_state.into_os_string(),
            "--site-packages".into(),
            prepared.site_packages.clone().into_os_string(),
        ],
        working_directory: prepared.state.clone(),
        environment,
    };
    let group = WorkerGroup::new().map_err(|_| "JOB_CREATE_FAILED")?;
    let worker = group
        .spawn_captured(&spec, CaptureLimits::default())
        .map_err(|_| "SPAWN_FAILED")?;
    // Drop our extra environment copy immediately after launch. Token material
    // remains only in proof memory and the child's explicit initial environment.
    drop(spec);
    let mut checks = Vec::new();
    let mut facts = json!({});
    let application = if fail_after_ready {
        worker
            .wait_ready(Duration::from_secs(45))
            .map_err(|_| "READINESS_FAILED")
            .and(Err("FIXTURE_FAILURE_AFTER_READY"))
    } else {
        exercise(
            &prepared,
            &group,
            &worker,
            &token,
            &wrong_token,
            &mut checks,
            &mut facts,
        )
    };
    // The unchanged diagnostic has no cooperative shutdown endpoint. This is an
    // explicit forced retirement of this one owned Job, never production teardown.
    let cleanup = group.retire_captured(&worker, 7, Duration::from_secs(10));
    let snapshot = worker.output_snapshot();
    let cleanup_ok = cleanup.is_ok()
        && group.active_count().is_ok_and(|count| count == 0)
        && snapshot
            .as_ref()
            .is_ok_and(|output| output.stdout_eof && output.stderr_eof);
    let unchanged = prepared.verify_unchanged();
    let scan = scan_state(&prepared.state, &[token.as_bytes(), wrong_token.as_bytes()]);
    let passed = application.is_ok() && cleanup_ok && unchanged.is_ok() && scan.is_ok();
    let report = json!({
        "mode": "rust-owned-retained-http-subset-v1",
        "proof_executable_sha256": executable_hash,
        "passed": passed,
        "stock_server_started": false,
        "gateway_available": false,
        "production_backend": false,
        "gpu_used": false,
        "upstream_handlers_modified": false,
        "diagnostic_helper_policy": "resolved-drive-comparison-v2",
        "diagnostic_helper_policy_sha256": prepared.policy_hash,
        "diagnostic_state_adapter": "short-equivalent-dos-state-v1",
        "diagnostic_state_max_utf16_units": 240,
        "fixture_failure_after_ready": fail_after_ready,
        "dependency_tree_fully_attested": false,
        "os_filesystem_sandbox": false,
        "checks": checks,
        "facts": facts,
        "application_error": application.err(),
        "retirement": {
            "cooperative": false,
            "forced_owned_job": true,
            "verified": cleanup_ok,
            "root_exit_code": cleanup.as_ref().ok().map(|result| result.exit_code),
            "job_empty": group.active_count().is_ok_and(|count| count == 0),
            "stdout_eof": snapshot.as_ref().is_ok_and(|output| output.stdout_eof),
            "stderr_eof": snapshot.as_ref().is_ok_and(|output| output.stderr_eof),
        },
        "stdout_bytes": snapshot.as_ref().ok().map(|output| output.stdout_bytes),
        "stderr_bytes": snapshot.as_ref().ok().map(|output| output.stderr_bytes),
        "source_pins_unchanged": unchanged.is_ok(),
        "source_error": unchanged.err(),
        "credential_scan_complete": scan.is_ok(),
        "credential_scan_scope": "synthetic state relative paths and file contents; serialized report bytes",
        "credential_bytes_persisted": if scan.is_ok() { Some(false) } else { None },
        "credential_scan_error": scan.as_ref().err(),
        "scanned_state_bytes": scan.ok(),
        "elapsed_seconds": start.elapsed().as_secs_f64(),
    });
    let bytes = serde_json::to_vec_pretty(&report).map_err(|_| "REPORT_FAILED")?;
    if contains(&bytes, token.as_bytes()) || contains(&bytes, wrong_token.as_bytes()) {
        return Err("REPORT_CREDENTIAL_REJECTED");
    }
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&prepared.report)
        .and_then(|mut output| output.write_all(&bytes))
        .map_err(|_| "REPORT_FAILED")?;
    if passed {
        Ok(())
    } else {
        Err("VERIFICATION_FAILED")
    }
}

fn exercise(
    prepared: &Prepared,
    group: &WorkerGroup,
    worker: &CapturedWorker,
    token: &str,
    wrong_token: &str,
    checks: &mut Vec<&'static str>,
    facts: &mut Value,
) -> ProofResult<()> {
    let port = worker
        .wait_ready(Duration::from_secs(45))
        .map_err(|_| "READINESS_FAILED")?;
    let mut client = OwnedHttpClient::new(
        group,
        port,
        Limits {
            timeout: Duration::from_secs(5),
            ..Limits::default()
        },
    )
    .map_err(|_| "HTTP_CLIENT_FAILED")?;
    let authorized = [(HEADER, token)];
    let cases: [RejectionCase<'_>; 9] = [
        (
            Method::Get,
            "/api/config",
            vec![],
            None,
            401,
            "missing-token-rejected",
        ),
        (
            Method::Get,
            "/api/config",
            vec![(HEADER, wrong_token)],
            None,
            401,
            "wrong-token-rejected",
        ),
        (
            Method::Get,
            "/api/config",
            vec![(HEADER, token), (HEADER, token)],
            None,
            401,
            "duplicate-token-rejected",
        ),
        (
            Method::Post,
            "/api/config",
            authorized.to_vec(),
            Some(b"{}"),
            403,
            "config-mutation-rejected",
        ),
        (
            Method::Get,
            "/api/config?profile=default",
            authorized.to_vec(),
            None,
            403,
            "named-profile-rejected",
        ),
        (
            Method::Get,
            "/api/env",
            authorized.to_vec(),
            None,
            403,
            "unlisted-route-rejected",
        ),
        (
            Method::Get,
            "/api/config?include_defaults=invalid",
            authorized.to_vec(),
            None,
            422,
            "invalid-config-query-rejected",
        ),
        (
            Method::Get,
            "/api/sessions?order=invalid",
            authorized.to_vec(),
            None,
            400,
            "invalid-session-order-rejected",
        ),
        (
            Method::Get,
            "/api/sessions?limit=101",
            authorized.to_vec(),
            None,
            422,
            "oversized-session-limit-rejected",
        ),
    ];
    for (method, path, headers, body, status, check) in cases {
        live(worker, port)?;
        let response = client
            .request(method, path, &headers, body)
            .map_err(|error| error.code())?;
        if response.status_code() != status {
            return Err("REJECTION_STATUS_MISMATCH");
        }
        checks.push(check);
    }
    let config = get_json(&mut client, worker, port, "/api/config", &authorized)?;
    let object = config.as_object().ok_or("CONFIG_SHAPE_INVALID")?;
    if !config["model"].is_string()
        || !config["model_context_length"].is_i64()
        || object.keys().any(|key| key.starts_with('_'))
    {
        return Err("CONFIG_SHAPE_INVALID");
    }
    checks.push("unchanged-get-config-handler");
    let sessions = get_json(
        &mut client,
        worker,
        port,
        "/api/sessions?limit=20&order=recent",
        &authorized,
    )?;
    if sessions["total"] != 1 || sessions["offset"] != 0 || sessions["limit"] != 20 {
        return Err("SESSIONS_SHAPE_INVALID");
    }
    let rows = sessions["sessions"]
        .as_array()
        .ok_or("SESSIONS_SHAPE_INVALID")?;
    if rows.len() != 1 {
        return Err("SESSIONS_SHAPE_INVALID");
    }
    let row = rows[0].as_object().ok_or("SESSIONS_SHAPE_INVALID")?;
    if row.get("id") != Some(&json!("managed-diagnostic-session"))
        || !rows[0]["archived"].is_boolean()
        || !rows[0]["pinned"].is_boolean()
        || row.contains_key("system_prompt")
        || row.contains_key("model_config")
    {
        return Err("SESSIONS_SHAPE_INVALID");
    }
    checks.push("unchanged-get-sessions-handler");
    let identity = get_json(
        &mut client,
        worker,
        port,
        "/diagnostic/identity",
        &authorized,
    )?;
    let pid = identity["pid"]
        .as_u64()
        .and_then(|pid| u32::try_from(pid).ok())
        .ok_or("IDENTITY_INVALID")?;
    if identity["mode"] != "diagnostic-http-subset-v1"
        || identity["source_manifest_sha256"] != prepared.manifest_hash
        || identity["source_files"].as_u64() != Some(prepared.source_file_count as u64)
        || identity["retained_handlers"]
            != json!([
                "hermes_cli.web_routers.config_env.get_config",
                "hermes_cli.web_routers.sessions.get_sessions"
            ])
        || identity["policy_violations"]
            .as_array()
            .is_none_or(|values| !values.is_empty())
        || identity["environment_names"]
            .as_array()
            .is_none_or(|names| {
                names
                    .iter()
                    .any(|name| name == "HERMES_DIAGNOSTIC_SESSION_TOKEN")
            })
        || !group
            .contains_observed_pid(pid)
            .map_err(|_| "IDENTITY_MEMBERSHIP_FAILED")?
    {
        return Err("IDENTITY_INVALID");
    }
    live(worker, port)?;
    checks.push("authenticated-source-identity-and-job-membership");
    *facts = json!({
        "upstream_commit": config::UPSTREAM,
        "source_manifest_sha256": prepared.manifest_hash,
        "retained_handlers": identity["retained_handlers"],
        "source_files": prepared.source_file_count,
        "config_keys": object.keys().collect::<Vec<_>>(),
        "session_response_keys": sessions.as_object().ok_or("SESSIONS_SHAPE_INVALID")?.keys().collect::<Vec<_>>(),
        "session_row_keys": row.keys().collect::<Vec<_>>(),
        "auth_and_rejection_checks": 9,
        "established_socket_ownership_verified_before_credentials": true,
        "environment_token_consumed": true,
        "policy_violations": 0,
    });
    Ok(())
}

fn get_json(
    client: &mut OwnedHttpClient<'_>,
    worker: &CapturedWorker,
    port: u16,
    path: &str,
    headers: &[(&str, &str)],
) -> ProofResult<Value> {
    live(worker, port)?;
    let response = client
        .request(Method::Get, path, headers, None)
        .map_err(|error| error.code())?;
    if response.status_code() != 200 {
        return Err("HANDLER_STATUS_MISMATCH");
    }
    serde_json::from_slice(response.body()).map_err(|_| "HANDLER_JSON_INVALID")
}

fn live(worker: &CapturedWorker, port: u16) -> ProofResult<()> {
    if worker.readiness().map_err(|_| "READINESS_INVALIDATED")? != Some(port)
        || worker
            .worker()
            .wait_timeout(Duration::ZERO)
            .map_err(|_| "PROCESS_QUERY_FAILED")?
            .is_some()
    {
        return Err("WORKER_NOT_LIVE");
    }
    Ok(())
}

fn environment(state: &Path, token: &str) -> ProofResult<BTreeMap<String, OsString>> {
    let mut windows = [0u16; 32_768];
    let count =
        unsafe { GetWindowsDirectoryW(windows.as_mut_ptr(), windows.len() as u32) } as usize;
    if count == 0 || count >= windows.len() {
        return Err("WINDOWS_DIRECTORY_FAILED");
    }
    let windows = String::from_utf16(&windows[..count]).map_err(|_| "WINDOWS_DIRECTORY_FAILED")?;
    let mut result = BTreeMap::from([
        ("SystemRoot".into(), windows.clone().into()),
        ("WINDIR".into(), windows.into()),
    ]);
    for name in ["USERPROFILE", "HOME", "TEMP", "TMP", "HERMES_HOME"] {
        result.insert(name.into(), state.as_os_str().to_owned());
    }
    for (name, child) in [
        ("APPDATA", "roaming"),
        ("LOCALAPPDATA", "local"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
        ("HERMES_MANAGED_DIR", "managed"),
        ("HERMES_GATEWAY_LOCK_DIR", "locks"),
    ] {
        result.insert(name.into(), state.join(child).into_os_string());
    }
    for name in [
        "HERMES_SAFE_MODE",
        "HERMES_DISABLE_LAZY_INSTALLS",
        "HERMES_SKIP_CHMOD",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
    ] {
        result.insert(name.into(), "1".into());
    }
    result.insert("HERMES_DIAGNOSTIC_SESSION_TOKEN".into(), token.into());
    Ok(result)
}

fn synthetic_state_path(path: &Path) -> ProofResult<PathBuf> {
    let canonical = config::checked(path, true)?;
    let ordinary = short_drive_spelling(&canonical)?;
    if ordinary
        .canonicalize()
        .map_err(|_| "STATE_PATH_IDENTITY_FAILED")?
        != canonical
    {
        return Err("STATE_PATH_IDENTITY_FAILED");
    }
    Ok(ordinary)
}

// This fixture-only adapter is for a new synthetic SQLite home, never the
// executable, shared process owner, arbitrary renderer path or user profile.
// Retained Path.as_uri produces an invalid SQLite URI authority for \\?\ paths.
fn short_drive_spelling(path: &Path) -> ProofResult<PathBuf> {
    if !path.is_absolute() {
        return Err("DIAGNOSTIC_STATE_PATH_UNSUPPORTED");
    }
    let mut ordinary = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(prefix) => match prefix.kind() {
                Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => {
                    ordinary.push(format!("{}:", char::from(drive)))
                }
                _ => return Err("DIAGNOSTIC_STATE_PATH_UNSUPPORTED"),
            },
            Component::RootDir => ordinary.push(component.as_os_str()),
            Component::Normal(name) => {
                let text = name.to_str().ok_or("DIAGNOSTIC_STATE_PATH_UNSUPPORTED")?;
                if text.ends_with('.') || text.ends_with(' ') {
                    return Err("DIAGNOSTIC_STATE_PATH_UNSUPPORTED");
                }
                ordinary.push(name);
            }
            _ => return Err("DIAGNOSTIC_STATE_PATH_UNSUPPORTED"),
        }
    }
    if ordinary.as_os_str().encode_wide().count() > 240 {
        return Err("DIAGNOSTIC_STATE_PATH_UNSUPPORTED");
    }
    Ok(ordinary)
}

fn fresh_token() -> ProofResult<String> {
    let mut bytes = [0u8; 48];
    let status = unsafe {
        BCryptGenRandom(
            std::ptr::null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    if status < 0 {
        return Err("RANDOM_FAILED");
    }
    let result = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    bytes.fill(0);
    Ok(result)
}

fn contains(bytes: &[u8], token: &[u8]) -> bool {
    !token.is_empty() && bytes.windows(token.len()).any(|window| window == token)
}

fn scan_state(root: &Path, tokens: &[&[u8]]) -> ProofResult<u64> {
    let mut pending = vec![root.to_path_buf()];
    let mut total = 0u64;
    let mut entries = 0usize;
    while let Some(directory) = pending.pop() {
        config::checked(&directory, true)?;
        for entry in std::fs::read_dir(directory).map_err(|_| "SCAN_FAILED")? {
            let entry = entry.map_err(|_| "SCAN_FAILED")?;
            entries += 1;
            if entries > 4096 {
                return Err("SCAN_LIMIT_EXCEEDED");
            }
            let path: PathBuf = entry.path();
            let relative = path
                .strip_prefix(root)
                .map_err(|_| "SCAN_FAILED")?
                .to_string_lossy();
            if tokens
                .iter()
                .any(|token| contains(relative.as_bytes(), token))
            {
                return Err("CREDENTIAL_PERSISTED");
            }
            if entry.file_type().map_err(|_| "SCAN_FAILED")?.is_dir() {
                pending.push(path);
                continue;
            }
            config::checked(&path, false)?;
            let mut bytes = Vec::new();
            File::open(path)
                .map_err(|_| "SCAN_FAILED")?
                .take(64 * 1024 * 1024 + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| "SCAN_FAILED")?;
            total += bytes.len() as u64;
            if total > 64 * 1024 * 1024 {
                return Err("SCAN_LIMIT_EXCEEDED");
            }
            if tokens.iter().any(|token| contains(&bytes, token)) {
                return Err("CREDENTIAL_PERSISTED");
            }
        }
    }
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credential_scan_detects_binary_and_partial_sensitive_values() {
        assert!(contains(b"\0before-canary-after\xff", b"canary"));
        assert!(!contains(b"canar", b"canary"));
        assert!(!contains(b"anything", b""));
    }

    #[test]
    fn tokens_are_printable_independent_and_environment_only() {
        let first = fresh_token().unwrap();
        let second = fresh_token().unwrap();
        assert_eq!(first.len(), 96);
        assert_ne!(first, second);
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
        let values = environment(Path::new("C:\\synthetic-proof"), &first).unwrap();
        assert_eq!(
            values["HERMES_DIAGNOSTIC_SESSION_TOKEN"],
            OsString::from(first)
        );
        assert!(!values.keys().any(|name| name.eq_ignore_ascii_case("PATH")));
    }

    fn fixture_directory() -> PathBuf {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hermes-retained-source-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        root
    }

    #[test]
    fn import_shadows_are_rejected_before_any_worker_launch() {
        let root = fixture_directory();
        let source = root.join("module.py");
        std::fs::write(&source, "VALUE = 1\n").unwrap();
        assert_eq!(config::source_tree(&root, true).unwrap().len(), 1);
        let documentation = root.join("README.md");
        std::fs::write(&documentation, "inert documentation").unwrap();
        assert_eq!(config::source_tree(&root, false).unwrap().len(), 1);
        assert_eq!(
            config::source_tree(&root, true).unwrap_err(),
            "SOURCE_IMPORT_SHADOW"
        );
        std::fs::remove_file(&documentation).unwrap();
        for extension in ["pyc", "pyo", "pyd", "dll"] {
            let shadow = root.join(format!("module.{extension}"));
            std::fs::write(&shadow, b"synthetic shadow").unwrap();
            assert_eq!(
                config::source_tree(&root, false).unwrap_err(),
                "SOURCE_IMPORT_SHADOW"
            );
            std::fs::remove_file(shadow).unwrap();
        }
        let cache = root.join("__pycache__");
        std::fs::create_dir(&cache).unwrap();
        assert_eq!(
            config::source_tree(&root, false).unwrap_err(),
            "SOURCE_IMPORT_SHADOW"
        );
        std::fs::remove_dir(cache).unwrap();
        std::fs::remove_file(source).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn credential_scan_rejects_names_and_incomplete_overflow_scan() {
        let root = fixture_directory();
        let named = root.join("canary-state.bin");
        std::fs::write(&named, b"not secret").unwrap();
        assert_eq!(
            scan_state(&root, &[b"canary"]).unwrap_err(),
            "CREDENTIAL_PERSISTED"
        );
        std::fs::remove_file(named).unwrap();
        let large = root.join("oversized.bin");
        File::create(&large)
            .unwrap()
            .set_len(64 * 1024 * 1024 + 1)
            .unwrap();
        assert_eq!(
            scan_state(&root, &[b"canary"]).unwrap_err(),
            "SCAN_LIMIT_EXCEEDED"
        );
        std::fs::remove_file(large).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn synthetic_state_adapter_preserves_identity_and_refuses_unsafe_spellings() {
        let root = fixture_directory();
        let canonical = root.canonicalize().unwrap();
        let ordinary = synthetic_state_path(&canonical).unwrap();
        assert_eq!(ordinary.canonicalize().unwrap(), canonical);
        assert!(!ordinary.as_os_str().to_string_lossy().starts_with(r"\\?\"));
        for invalid in [
            r"\\?\C:\state.\home",
            r"\\?\C:\state \home",
            r"\\?\UNC\host\share\state",
            r"C:\state\..\home",
        ] {
            assert_eq!(
                short_drive_spelling(Path::new(invalid)).unwrap_err(),
                "DIAGNOSTIC_STATE_PATH_UNSUPPORTED"
            );
        }
        let long = format!(r"C:\{}\state", "segment".repeat(40));
        assert_eq!(
            short_drive_spelling(Path::new(&long)).unwrap_err(),
            "DIAGNOSTIC_STATE_PATH_UNSUPPORTED"
        );
        assert_eq!(
            short_drive_spelling(Path::new(r"\\?\C:\日本語\state")).unwrap(),
            PathBuf::from(r"C:\日本語\state")
        );
        std::fs::remove_dir(root).unwrap();
    }
}
