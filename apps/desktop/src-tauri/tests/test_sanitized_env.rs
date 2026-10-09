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

#[test]
fn test_spawned_process_inherits_no_parent_secrets_with_env_clear() {
    unsafe {
        std::env::set_var("SUPERVISOR_PARENT_SECRET", "leaked_secret_val_999");
        std::env::set_var("ANTHROPIC_API_KEY", "sk-ant-adversarial-secret");
    }

    let mut extra = HashMap::new();
    extra.insert("CHILD_TOKEN".to_string(), "token_123".to_string());

    let sanitized = build_sanitized_env(&extra, None);

    let mut cmd = std::process::Command::new("cmd.exe");
    cmd.args(["/c", "set"])
        .env_clear()
        .envs(&sanitized);

    let output = cmd.output().expect("Failed to execute cmd");
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(
        !stdout.contains("SUPERVISOR_PARENT_SECRET"),
        "Parent secret leaked through Command with env_clear!"
    );
    assert!(
        !stdout.contains("ANTHROPIC_API_KEY"),
        "Parent secret ANTHROPIC_API_KEY leaked through Command with env_clear!"
    );
    assert!(
        stdout.contains("CHILD_TOKEN=token_123"),
        "Sanitized extra var missing in child process!"
    );
    assert!(
        stdout.contains("PATH="),
        "Sanitized PATH missing in child process!"
    );
    assert!(
        stdout.contains("PYTHONUNBUFFERED=1"),
        "PYTHONUNBUFFERED missing in child process!"
    );
}

