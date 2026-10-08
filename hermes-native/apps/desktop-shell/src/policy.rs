use serde::Serialize;
use serde_json::Value;

pub const METHODS: &[&str] = &[
    "api",
    "getConnection",
    "getConnectionFor",
    "getGatewayWsUrl",
    "getGatewayWsUrlFor",
    "revalidateConnection",
    "touchBackend",
    "getVersion",
    "getBootProgress",
    "getRecentLogs",
    "getBootstrapState",
    "resetBootstrap",
    "revealLogs",
    "watchPreviewFile",
    "watchDirectory",
    "stopPreviewFileWatch",
];

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct HostError {
    pub code: &'static str,
    pub capability: String,
}

pub fn local_origin(url: &tauri::Url) -> bool {
    url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
        && ((url.scheme() == "http" && url.host_str() == Some("tauri.localhost"))
            || (url.scheme() == "tauri" && url.host_str() == Some("localhost")))
}

pub fn validate_request(method: &str, args: &[Value]) -> Result<(), HostError> {
    if !METHODS.contains(&method)
        || args.len() > 2
        || serde_json::to_vec(args).map_or(true, |bytes| bytes.len() > 65536)
    {
        return Err(HostError {
            code: "HERMES_HOST_INVALID_REQUEST",
            capability: "host-request".into(),
        });
    }
    Ok(())
}

pub fn request(method: &str, args: &[Value]) -> Result<Value, HostError> {
    validate_request(method, args)?;
    // No runtime owner or source route exists yet. Never fabricate connection,
    // model state, version provenance or successful API responses.
    Err(HostError {
        code: "HERMES_HOST_CAPABILITY_UNAVAILABLE",
        capability: method.into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn every_retained_method_has_explicit_unavailable_error() {
        for method in METHODS {
            let error = request(method, &[Value::Null]).unwrap_err();
            assert_eq!(error.code, "HERMES_HOST_CAPABILITY_UNAVAILABLE");
            assert_eq!(error.capability, *method);
        }
    }

    #[test]
    fn unknown_and_oversized_requests_do_not_dispatch() {
        for (method, args) in [
            ("runCommand", vec![]),
            ("api", vec![json!("x".repeat(65536))]),
            ("api", vec![Value::Null; 3]),
        ] {
            assert_eq!(
                request(method, &args).unwrap_err().code,
                "HERMES_HOST_INVALID_REQUEST"
            );
        }
    }

    #[test]
    fn origin_requires_exact_bundled_authority() {
        for accepted in [
            "http://tauri.localhost/index.html",
            "tauri://localhost/index.html",
        ] {
            assert!(local_origin(&tauri::Url::parse(accepted).unwrap()));
        }
        for denied in [
            "https://tauri.localhost/index.html",
            "http://tauri.localhost:99/",
            "http://tauri.localhost.example/",
            "http://user@tauri.localhost/",
            "http://localhost/",
            "file:///index.html",
        ] {
            assert!(!local_origin(&tauri::Url::parse(denied).unwrap()));
        }
    }
}
