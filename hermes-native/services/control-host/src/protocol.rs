use crate::{json, ControlError};
use serde_json::{Map, Value};

pub const OPERATIONS: &[&str] = &[
    "runtime.status",
    "profiles.schema",
    "profiles.validate",
    "profiles.list",
    "profiles.get",
    "profiles.save",
    "profiles.delete",
];
const PROFILE_FIELDS: &[&str] = &[
    "artifact_id",
    "revision",
    "model_name",
    "expected_model_path",
    "context_length",
    "cache_size",
    "cache_mode",
    "max_batch_size",
    "chunk_size",
    "vision",
];

pub(crate) fn exact<'a>(value: &'a Value, names: &[&str]) -> Option<&'a Map<String, Value>> {
    let object = value.as_object()?;
    (object.len() == names.len() && names.iter().all(|name| object.contains_key(*name)))
        .then_some(object)
}
fn text(value: &Value, max: usize) -> bool {
    value.as_str().is_some_and(|text| {
        !text.trim().is_empty() && text.len() <= max && !text.chars().any(char::is_control)
    })
}
fn identifier(value: &Value) -> bool {
    value.as_str().is_some_and(|text| {
        !text.is_empty()
            && text.len() <= 64
            && text.as_bytes()[0].is_ascii_alphanumeric()
            && text
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
    })
}
fn revision(value: &Value) -> bool {
    value
        .as_i64()
        .is_some_and(|value| value > 0 && value < i64::MAX - 1)
}
fn profile(value: &Value, normalized: bool) -> bool {
    let Some(object) = value.as_object() else {
        return false;
    };
    if object
        .keys()
        .any(|key| !PROFILE_FIELDS.contains(&key.as_str()))
        || !PROFILE_FIELDS[..4]
            .iter()
            .all(|key| object.contains_key(*key))
        || (normalized && object.len() != PROFILE_FIELDS.len())
    {
        return false;
    }
    object.iter().all(|(key, value)| match key.as_str() {
        "context_length" | "cache_size" | "max_batch_size" | "chunk_size" => {
            value.as_i64().is_some()
        }
        "vision" => value.is_boolean(),
        _ => text(value, 4096),
    }) && serde_json::to_vec(value).is_ok_and(|bytes| bytes.len() <= 16_384)
}

pub(crate) fn validate_request(operation: &str, params: &Value) -> Result<(), ControlError> {
    let valid = match operation {
        "runtime.status" | "profiles.schema" | "profiles.list" => exact(params, &[]).is_some(),
        "profiles.validate" => {
            exact(params, &["profile"]).is_some() && profile(&params["profile"], false)
        }
        "profiles.get" => {
            exact(params, &["profile_id"]).is_some() && identifier(&params["profile_id"])
        }
        "profiles.delete" => {
            exact(params, &["profile_id", "expected_revision"]).is_some()
                && identifier(&params["profile_id"])
                && revision(&params["expected_revision"])
        }
        "profiles.save" => {
            exact(
                params,
                &["profile_id", "name", "expected_revision", "profile"],
            )
            .is_some()
                && identifier(&params["profile_id"])
                && text(&params["name"], 128)
                && (params["expected_revision"].is_null() || revision(&params["expected_revision"]))
                && profile(&params["profile"], false)
        }
        _ => return Err(ControlError::unavailable()),
    };
    if valid {
        Ok(())
    } else {
        Err(ControlError::invalid())
    }
}

pub(crate) fn hello(bytes: &[u8]) -> bool {
    json::decode(bytes).is_ok_and(|value| {
        exact(&value, &["type", "protocol", "service", "runtime_attached"]).is_some()
            && value["type"] == "ready"
            && value["protocol"] == "hermes-control-v1"
            && value["service"] == "hermes-control-worker"
            && value["runtime_attached"] == false
    })
}

pub(crate) fn response(
    bytes: &[u8],
    request_id: &str,
    operation: &str,
    params: &Value,
) -> Result<Value, ControlError> {
    let value = json::decode(bytes).map_err(|_| ControlError::protocol())?;
    if value["id"].as_str() != Some(request_id) {
        return Err(ControlError::protocol());
    }
    if exact(&value, &["id", "error"]).is_some() {
        let error = &value["error"];
        if exact(error, &["code", "message"]).is_none() || !text(&error["message"], 256) {
            return Err(ControlError::protocol());
        }
        // Never echo arbitrary child error text. Only finite application errors
        // survive; storage/protocol/session errors retire this generation.
        return Err(match error["code"].as_str() {
            Some("INVALID_PARAMS") => {
                ControlError::application("INVALID_PARAMS", "The operation parameters are invalid.")
            }
            Some("INVALID_PROFILE") => ControlError::application(
                "INVALID_PROFILE",
                "The load profile is invalid or exceeds service limits.",
            ),
            Some("PROFILE_NOT_FOUND") => {
                ControlError::application("PROFILE_NOT_FOUND", "The saved profile does not exist.")
            }
            Some("REVISION_CONFLICT") => ControlError::application(
                "REVISION_CONFLICT",
                "The saved profile changed; read it again.",
            ),
            Some("PROFILE_LIMIT") => ControlError::application(
                "PROFILE_LIMIT",
                "The saved profile limit has been reached.",
            ),
            _ => ControlError::protocol(),
        });
    }
    if exact(&value, &["id", "result"]).is_none()
        || !valid_result(operation, &value["result"], params)
    {
        return Err(ControlError::protocol());
    }
    Ok(value["result"].clone())
}

fn summary(value: &Value) -> bool {
    exact(value, &["profile_id", "name", "revision"]).is_some()
        && identifier(&value["profile_id"])
        && text(&value["name"], 128)
        && revision(&value["revision"])
}
fn schema(value: &Value) -> bool {
    if exact(
        value,
        &[
            "schema_source",
            "fields",
            "validation_scope",
            "artifact_verification",
            "limits",
        ],
    )
    .is_none()
        || value["schema_source"] != "hermes_inference.LoadProfile"
        || value["validation_scope"] != "schema"
        || value["artifact_verification"] != false
        || value["limits"]
            != serde_json::json!({"max_profiles":128,"profile_bytes":16384,"text_bytes":4096})
    {
        return false;
    }
    let Some(fields) = value["fields"].as_array() else {
        return false;
    };
    if fields.len() != PROFILE_FIELDS.len() {
        return false;
    }
    let mut seen = std::collections::BTreeSet::new();
    fields.iter().all(|field| {
        let Some(name) = field["name"].as_str() else {
            return false;
        };
        if !PROFILE_FIELDS.contains(&name) || !seen.insert(name) || !field["required"].is_boolean()
        {
            return false;
        }
        let required = PROFILE_FIELDS[..4].contains(&name);
        if field["required"] != required
            || exact(
                field,
                if required {
                    &["name", "type", "required"]
                } else {
                    &["name", "type", "required", "default"]
                },
            )
            .is_none()
        {
            return false;
        }
        let expected_type = if name == "vision" {
            "bool"
        } else if [
            "context_length",
            "cache_size",
            "max_batch_size",
            "chunk_size",
        ]
        .contains(&name)
        {
            "int"
        } else {
            "str"
        };
        field["type"] == expected_type
            && (required
                || match expected_type {
                    "bool" => field["default"].is_boolean(),
                    "int" => field["default"].as_i64().is_some(),
                    _ => text(&field["default"], 4096),
                })
    })
}

fn valid_result(operation: &str, value: &Value, params: &Value) -> bool {
    match operation {
        "service.describe" => {
            let mut methods: Vec<&str> = OPERATIONS.to_vec();
            methods.extend(["service.describe", "service.shutdown"]);
            methods.sort_unstable();
            let mut actual = value["methods"]
                .as_array()
                .and_then(|values| values.iter().map(Value::as_str).collect::<Option<Vec<_>>>())
                .unwrap_or_default();
            actual.sort_unstable();
            exact(
                value,
                &[
                    "protocol",
                    "service",
                    "methods",
                    "max_frame_bytes",
                    "max_requests",
                    "runtime_attached",
                    "admission_allowed",
                ],
            )
            .is_some()
                && value["protocol"] == "hermes-control-v1"
                && value["service"] == "hermes-control-worker"
                && methods == actual
                && value["max_frame_bytes"] == 65_536
                && value["max_requests"] == 4096
                && value["runtime_attached"] == false
                && value["admission_allowed"] == false
        }
        "service.shutdown" => value == &serde_json::json!({"stopping":true}),
        "runtime.status" => {
            value
                == &serde_json::json!({"state":"detached","runtime_attached":false,"admission_allowed":false,"active_profile":null,"engine_observed":false})
        }
        "profiles.schema" => schema(value),
        "profiles.validate" => {
            exact(value, &["profile", "validation_scope", "artifact_verified"]).is_some()
                && profile(&value["profile"], true)
                && value["validation_scope"] == "schema"
                && value["artifact_verified"] == false
        }
        "profiles.list" => {
            exact(value, &["profiles"]).is_some()
                && value["profiles"].as_array().is_some_and(|profiles| {
                    profiles.len() <= 128
                        && profiles.iter().all(summary)
                        && profiles
                            .iter()
                            .map(|profile| profile["profile_id"].as_str())
                            .collect::<std::collections::BTreeSet<_>>()
                            .len()
                            == profiles.len()
                })
        }
        "profiles.get" => {
            exact(
                value,
                &[
                    "profile_id",
                    "name",
                    "revision",
                    "profile",
                    "validation_scope",
                ],
            )
            .is_some()
                && value["profile_id"] == params["profile_id"]
                && identifier(&value["profile_id"])
                && text(&value["name"], 128)
                && revision(&value["revision"])
                && profile(&value["profile"], true)
                && value["validation_scope"] == "schema"
        }
        "profiles.save" => {
            exact(value, &["profile_id", "revision", "validation_scope"]).is_some()
                && value["profile_id"] == params["profile_id"]
                && identifier(&value["profile_id"])
                && revision(&value["revision"])
                && value["validation_scope"] == "schema"
        }
        "profiles.delete" => {
            value == &serde_json::json!({"deleted":true,"profile_id":params["profile_id"]})
        }
        _ => false,
    }
}
