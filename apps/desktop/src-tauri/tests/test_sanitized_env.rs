use friday_supervisor::processes::build_sanitized_env;
use std::collections::HashMap;

#[test]
fn test_sanitized_environment_strips_parent_secrets() {
    // Inject a sensitive parent environment variable
    unsafe {
        std::env::set_var("LEAKED_AWS_SECRET", "super_secret_value_12345");
        std::env::set_var("ANTHROPIC_API_KEY", "sk-ant-test-danger");
    }

    let mut extra = HashMap::new();
    extra.insert("FRIDAY_BEARER_TOKEN".to_string(), "ephemeral-token".to_string());

    let sanitized = build_sanitized_env(&extra, None);

    // Assert sensitive parent vars are NOT present
    assert!(!sanitized.contains_key("LEAKED_AWS_SECRET"));
    assert!(!sanitized.contains_key("ANTHROPIC_API_KEY"));

    // Assert whitelisted system vars ARE present
    assert!(sanitized.contains_key("PATH"));
    assert!(sanitized.contains_key("PYTHONUNBUFFERED"));
    assert_eq!(sanitized.get("FRIDAY_BEARER_TOKEN").unwrap(), "ephemeral-token");
}
