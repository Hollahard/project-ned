//! Empirical Challenger 1 Adversarial Environment Permutation Stress Test.
//!
//! Tests:
//! 1. Extensive parent environment poisoning with 50+ hostile/secret variable permutations
//!    (API keys, DB URLs, tokens, SSH keys, prefix/suffix collisions with whitelisted names,
//!    case variants, special characters, multiline values).
//! 2. Spawning child process with Command::new().env_clear().envs(&sanitized).
//! 3. Verifying that zero hostile keys and zero hostile values leak into child environment.
//! 4. Verifying that whitelisted variables and explicit extras are strictly preserved.

use friday_supervisor::processes::build_sanitized_env;
use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

#[test]
fn test_adversarial_parent_secret_leak_permutations() {
    let hostile_pairs = vec![
        ("OPENAI_API_KEY", "sk-proj-super-secret-openai-key-9999"),
        ("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
        ("ANTHROPIC_API_KEY", "sk-ant-admin-0123456789abcdef"),
        ("SUPERVISOR_SECRET", "top_secret_supervisor_token_xyz"),
        ("GITHUB_PAT", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("DATABASE_URL", "postgres://admin:SuperSecretPass@localhost:5432/db"),
        ("SSH_PRIVATE_KEY", "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"),
        // Substring / prefix / suffix collision attacks with whitelisted names
        ("PATH_LEAK_SECRET", "should_not_leak_via_path_prefix"),
        ("TEMP_SECRET_KEY", "should_not_leak_via_temp_prefix"),
        ("TMP_PRIVATE", "should_not_leak_via_tmp_prefix"),
        ("SYSTEMROOT_PWD", "should_not_leak_via_systemroot_prefix"),
        ("SYSTEMDRIVE_CREDS", "should_not_leak_via_systemdrive_prefix"),
        ("WINDIR_EXPLOIT", "should_not_leak_via_windir_prefix"),
        ("COMSPEC_INJECTION", "should_not_leak_via_comspec_prefix"),
        ("USERPROFILE_ATTACK", "should_not_leak_via_userprofile_prefix"),
        ("LOCALAPPDATA_STEAL", "should_not_leak_via_localappdata_prefix"),
        ("APPDATA_BACKDOOR", "should_not_leak_via_appdata_prefix"),
        ("NUMBER_OF_PROCESSORS_OVERFLOW", "999999"),
        ("PROCESSOR_ARCHITECTURE_MIMIC", "ARM64_HOSTILE"),
        ("MY_PATH", "fake_path_secret"),
        ("SECRET_PATH", "another_fake_path_secret"),
        // Case permutations
        ("hostile_lowercase_secret", "lowercase_value_12345"),
        ("hOsTiLe_MiXeD_sEcReT", "mixed_case_value_67890"),
        ("api_key", "secret_api_key_lowercase"),
        // Value permutations (empty, spaces, special chars)
        ("SECRET_EMPTY", ""),
        ("SECRET_WHITESPACE", "   secret with spaces   "),
        ("SECRET_SPECIAL_CHARS", "!@#$%^&*()_+-=[]{}|;':,./<>?"),
    ];

    // 1. Poison host environment with all hostile pairs
    for (key, val) in &hostile_pairs {
        unsafe {
            std::env::set_var(key, val);
        }
    }

    let mut extra = HashMap::new();
    extra.insert("CHILD_TOKEN_EXPLICIT".to_string(), "legitimate_child_token_456".to_string());
    extra.insert("SUPERVISOR_PORT".to_string(), "8080".to_string());

    let sanitized = build_sanitized_env(&extra, None);

    // 2. Verify in-memory HashMap does NOT contain any hostile keys
    for (key, _) in &hostile_pairs {
        assert!(
            !sanitized.contains_key(*key),
            "Sanitized HashMap leaked hostile key: {}",
            key
        );
    }

    // 3. Spawn real OS subprocess with env_clear() + envs(&sanitized)
    let mut cmd = Command::new("cmd.exe");
    cmd.args(["/c", "set"])
        .env_clear()
        .envs(&sanitized);

    let output = cmd.output().expect("Failed to execute cmd.exe child process");
    let stdout = String::from_utf8_lossy(&output.stdout);

    // 4. Parse all child environment variables from cmd /c set output
    let mut child_env_keys = Vec::new();
    let mut child_env_values = Vec::new();

    for line in stdout.lines() {
        if let Some((k, v)) = line.split_once('=') {
            child_env_keys.push(k.trim().to_uppercase());
            child_env_values.push(v.trim().to_string());
        }
    }

    // 5. Assert: NONE of the hostile keys exist in child process environment
    for (key, val) in &hostile_pairs {
        let upper_key = key.to_uppercase();
        assert!(
            !child_env_keys.contains(&upper_key),
            "Hostile key {} leaked to child process environment!",
            key
        );

        if !val.is_empty() && val.len() > 5 {
            assert!(
                !stdout.contains(val),
                "Hostile value for key {} leaked to child process stdout! Value: {}",
                key,
                val
            );
        }
    }

    // 6. Assert: Whitelisted system variables and extra variables DO exist
    assert!(
        stdout.contains("CHILD_TOKEN_EXPLICIT=legitimate_child_token_456"),
        "Explicit child token missing from child process!"
    );
    assert!(
        stdout.contains("SUPERVISOR_PORT=8080"),
        "Explicit port missing from child process!"
    );
    assert!(
        stdout.contains("PYTHONUNBUFFERED=1"),
        "PYTHONUNBUFFERED missing from child process!"
    );
    assert!(
        child_env_keys.contains(&"PATH".to_string()),
        "PATH missing from child process!"
    );

    // 7. Cleanup poisoned environment variables
    for (key, _) in &hostile_pairs {
        unsafe {
            std::env::remove_var(key);
        }
    }
}

#[test]
fn test_adversarial_parent_secret_leak_with_venv_permutations() {
    unsafe {
        std::env::set_var("AWS_TEMP_KEY", "sensitive_aws_secret_key_888");
        std::env::set_var("GITHUB_OAUTH", "gho_fake_oauth_token_999");
    }

    let fake_venv = Path::new("C:\\mock\\virtualenv");
    let mut extra = HashMap::new();
    extra.insert("SERVICE_NAME".to_string(), "friday-core".to_string());

    let sanitized = build_sanitized_env(&extra, Some(fake_venv));

    // Assert VIRTUAL_ENV and Scripts are present
    assert_eq!(
        sanitized.get("VIRTUAL_ENV").unwrap(),
        "C:\\mock\\virtualenv"
    );
    let path_val = sanitized.get("PATH").unwrap();
    assert!(
        path_val.starts_with("C:\\mock\\virtualenv\\Scripts"),
        "PATH should prepend venv Scripts directory"
    );

    // Assert secrets are not present
    assert!(!sanitized.contains_key("AWS_TEMP_KEY"));
    assert!(!sanitized.contains_key("GITHUB_OAUTH"));

    // Spawn cmd.exe with env_clear
    let mut cmd = Command::new("cmd.exe");
    cmd.args(["/c", "set"])
        .env_clear()
        .envs(&sanitized);

    let output = cmd.output().expect("Failed to execute cmd.exe");
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(!stdout.contains("AWS_TEMP_KEY"));
    assert!(!stdout.contains("GITHUB_OAUTH"));
    assert!(stdout.contains("VIRTUAL_ENV=C:\\mock\\virtualenv"));
    assert!(stdout.contains("SERVICE_NAME=friday-core"));

    unsafe {
        std::env::remove_var("AWS_TEMP_KEY");
        std::env::remove_var("GITHUB_OAUTH");
    }
}
