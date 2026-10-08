use crate::{json, CatalogError};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeSet;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Issue {
    code: String,
    category: String,
    file: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Report {
    schema: u32,
    model: String,
    status: String,
    format: String,
    declared_architectures: Vec<String>,
    declared_bits: Option<f64>,
    observed_shard_count: u64,
    observed_tensor_count: u64,
    index_tensor_count: Option<u64>,
    missing_shards: Vec<String>,
    metadata_fingerprint: Option<String>,
    fingerprint_partial: bool,
    fingerprint_scope: String,
    issues: Vec<Issue>,
    issues_truncated: bool,
    bytes_read: u64,
    runtime_compatible: Value,
    load_certified: bool,
    weights_content_hashed: bool,
    weight_payload_bytes_read: u64,
}
const CATEGORIES: &[&str] = &[
    "security",
    "changed",
    "invalid",
    "incomplete",
    "inaccessible",
    "unsupported",
];
pub(crate) fn basename(value: &str) -> bool {
    if value.is_empty()
        || value.chars().count() > 240
        || value == "."
        || value == ".."
        || value.ends_with(['.', ' '])
        || value
            .chars()
            .any(|c| c.is_control() || "/\\:*?\"<>|".contains(c))
    {
        return false;
    }
    let stem = value.split('.').next().unwrap_or("").to_ascii_uppercase();
    !matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        && !(stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && stem.as_bytes()[3].is_ascii_digit())
}
pub(crate) fn response(bytes: &[u8], model: &str) -> Result<Value, CatalogError> {
    let value = json::decode(bytes).map_err(|_| CatalogError::protocol())?;
    const KEYS: &[&str] = &[
        "schema",
        "model",
        "status",
        "format",
        "declared_architectures",
        "declared_bits",
        "observed_shard_count",
        "observed_tensor_count",
        "index_tensor_count",
        "missing_shards",
        "metadata_fingerprint",
        "fingerprint_partial",
        "fingerprint_scope",
        "issues",
        "issues_truncated",
        "bytes_read",
        "runtime_compatible",
        "load_certified",
        "weights_content_hashed",
        "weight_payload_bytes_read",
    ];
    let object = value.as_object().ok_or_else(CatalogError::protocol)?;
    if object.len() != KEYS.len() || KEYS.iter().any(|key| !object.contains_key(*key)) {
        return Err(CatalogError::protocol());
    }
    let report: Report =
        serde_json::from_value(value.clone()).map_err(|_| CatalogError::protocol())?;
    if report.schema != 1
        || report.model != model
        || !basename(&report.model)
        || !(report.status == "metadata_inspected" || CATEGORIES.contains(&report.status.as_str()))
        || ![
            "EXL3",
            "EXL2",
            "GPTQ",
            "GGUF_unsupported",
            "hf_unquantized_or_unspecified",
            "unknown",
        ]
        .contains(&report.format.as_str())
        || report.declared_architectures.len() > 8
        || report
            .declared_architectures
            .iter()
            .any(|s| s.chars().count() > 128 || s.chars().any(char::is_control))
        || report
            .declared_bits
            .is_some_and(|n| !n.is_finite() || n <= 0.0 || n > 1_000_000.0)
        || report.observed_shard_count > 64
        || report.observed_tensor_count > 500000
        || report.index_tensor_count.is_some_and(|n| n > 500000)
        || report.missing_shards.len() > 64
        || report
            .missing_shards
            .iter()
            .any(|s| !basename(s) || !s.ends_with(".safetensors"))
        || report.missing_shards.iter().collect::<BTreeSet<_>>().len()
            != report.missing_shards.len()
        || report.metadata_fingerprint.as_ref().is_some_and(|s| {
            s.len() != 64
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
        || report.fingerprint_scope != "metadata_files_weight_headers_and_file_sizes"
        || report.issues.len() > 32
        || report.issues.iter().any(|i| {
            i.code.is_empty()
                || i.code.len() > 64
                || !i
                    .code
                    .bytes()
                    .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
                || !CATEGORIES.contains(&i.category.as_str())
                || i.file.as_ref().is_some_and(|f| !basename(f))
        })
        || report.bytes_read > 256 * 1024 * 1024
        || !report.runtime_compatible.is_null()
        || report.load_certified
        || report.weights_content_hashed
        || report.weight_payload_bytes_read != 0
        || (!report.fingerprint_partial
            && (!report.issues.is_empty()
                || report.issues_truncated
                || !report.missing_shards.is_empty()))
        || (report.status == "metadata_inspected"
            && (report.fingerprint_partial || report.metadata_fingerprint.is_none()))
    {
        return Err(CatalogError::protocol());
    }
    Ok(value)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn good() -> Value {
        serde_json::json!({"schema":1,"model":"model","status":"incomplete","format":"EXL3","declared_architectures":[],"declared_bits":null,"observed_shard_count":0,"observed_tensor_count":0,"index_tensor_count":null,"missing_shards":[],"metadata_fingerprint":null,"fingerprint_partial":true,"fingerprint_scope":"metadata_files_weight_headers_and_file_sizes","issues":[],"issues_truncated":false,"bytes_read":0,"runtime_compatible":null,"load_certified":false,"weights_content_hashed":false,"weight_payload_bytes_read":0})
    }
    #[test]
    fn required_nullable_fields_cannot_be_omitted() {
        for field in [
            "declared_bits",
            "index_tensor_count",
            "metadata_fingerprint",
            "runtime_compatible",
        ] {
            let mut value = good();
            value.as_object_mut().unwrap().remove(field);
            assert!(response(&serde_json::to_vec(&value).unwrap(), "model").is_err());
        }
        assert!(response(&serde_json::to_vec(&good()).unwrap(), "model").is_ok());
    }
    #[test]
    fn duplicate_unknown_and_certification_fields_rejected() {
        assert!(response(br#"{"schema":1,"schema":1}"#, "model").is_err());
        for (key, value) in [
            ("api_key", Value::String("canary".into())),
            ("load_certified", Value::Bool(true)),
            ("weight_payload_bytes_read", Value::from(1)),
        ] {
            let mut report = good();
            report[key] = value;
            assert!(response(&serde_json::to_vec(&report).unwrap(), "model").is_err());
        }
    }
    #[test]
    fn basename_rejects_devices_ads_and_separators() {
        for name in [
            "..",
            "AUX",
            "com0.txt",
            "foo:bar",
            "foo/../bar",
            "foo.",
            "foo ",
        ] {
            assert!(!basename(name));
        }
        assert!(basename("--help"));
    }
}
