//! Evidence validation for a disposable, local-only browser feasibility fixture.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub origin: String,
    pub path: String,
    pub document_url: String,
    pub cookie: String,
    pub storage: Option<String>,
    pub hermes_bridge: String,
    pub tauri_bridge: String,
    pub ipc_bridge: String,
}

pub fn allows_navigation(origin: &str, url: &str) -> bool {
    url == origin || url.starts_with(&format!("{origin}/"))
}

pub fn validate_snapshot(
    snapshot: &Snapshot,
    expected_origin: &str,
    expected_path: &str,
    expected_marker: Option<&str>,
) -> Result<(), String> {
    if snapshot.origin != expected_origin
        || snapshot.path != expected_path
        || snapshot.document_url != format!("{expected_origin}{expected_path}")
    {
        return Err("navigation origin or path differs from fixture expectation".into());
    }
    let cookie = expected_marker.map_or_else(String::new, |value| format!("partition={value}"));
    if snapshot.cookie != cookie || snapshot.storage.as_deref() != expected_marker {
        return Err("cookie/localStorage partition expectation failed".into());
    }
    if [
        &snapshot.hermes_bridge,
        &snapshot.tauri_bridge,
        &snapshot.ipc_bridge,
    ]
    .iter()
    .any(|value| value.as_str() != "undefined")
    {
        return Err("guest received an unexpected privileged or IPC bridge".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot() -> Snapshot {
        Snapshot {
            origin: "http://127.0.0.1:43210".into(),
            path: "/initial".into(),
            document_url: "http://127.0.0.1:43210/initial".into(),
            cookie: "partition=A".into(),
            storage: Some("A".into()),
            hermes_bridge: "undefined".into(),
            tauri_bridge: "undefined".into(),
            ipc_bridge: "undefined".into(),
        }
    }

    #[test]
    fn navigation_allowlist_rejects_host_prefix_and_other_ports() {
        let origin = "http://127.0.0.1:43210";
        assert!(allows_navigation(origin, &format!("{origin}/next")));
        for target in [
            "http://127.0.0.1:432100/",
            "http://127.0.0.1:43210@elsewhere.invalid/",
            "http://127.0.0.1:9/",
            "https://example.invalid/",
            "javascript:alert(1)",
        ] {
            assert!(!allows_navigation(origin, target));
        }
    }

    #[test]
    fn evidence_requires_independent_cookie_and_local_storage() {
        let mut evidence = snapshot();
        assert!(validate_snapshot(&evidence, &evidence.origin, "/initial", Some("A")).is_ok());
        assert!(validate_snapshot(&evidence, &evidence.origin, "/initial", None).is_err());
        evidence.storage = Some("B".into());
        assert!(validate_snapshot(&evidence, &evidence.origin, "/initial", Some("A")).is_err());
    }

    #[test]
    fn privileged_bridge_is_a_failure_even_with_correct_storage() {
        let mut evidence = snapshot();
        evidence.hermes_bridge = "object".into();
        assert!(validate_snapshot(&evidence, &evidence.origin, "/initial", Some("A")).is_err());
    }

    #[test]
    fn error_document_cannot_count_as_the_expected_loaded_page() {
        let mut evidence = snapshot();
        evidence.document_url = "chrome-error://chromewebdata/".into();
        assert!(validate_snapshot(&evidence, &evidence.origin, "/initial", Some("A")).is_err());
    }
}
