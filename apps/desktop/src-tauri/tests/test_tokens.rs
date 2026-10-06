use friday_supervisor::approvals::{compute_args_hash, ApprovalManager};

#[test]
fn test_canonical_args_hash_is_order_independent() {
    let args1 = serde_json::json!({
        "b": "value_b",
        "a": "value_a",
        "nested": {
            "z": 100,
            "y": 200
        }
    });

    let args2 = serde_json::json!({
        "nested": {
            "y": 200,
            "z": 100
        },
        "a": "value_a",
        "b": "value_b"
    });

    let hash1 = compute_args_hash(&args1);
    let hash2 = compute_args_hash(&args2);

    assert_eq!(hash1, hash2, "Canonical hash must be independent of key order");
}

#[test]
fn test_approval_manager_mint_and_single_use_consume() {
    let manager = ApprovalManager::new("secret-key-123".to_string(), 60);
    let args = serde_json::json!({ "command": "cargo test" });

    let (token, hash) = manager
        .mint_token("terminal.exec", &args)
        .expect("Minting token should succeed");

    assert!(token.contains('.'), "Token must contain dot separator");
    assert!(!hash.is_empty(), "Hash must not be empty");

    // First consumption succeeds
    let consume1 = manager.validate_and_consume(&token, "terminal.exec", &args);
    assert!(consume1.is_ok(), "First consumption must succeed");

    // Second consumption fails (single-use invariant)
    let consume2 = manager.validate_and_consume(&token, "terminal.exec", &args);
    assert!(
        consume2.is_err(),
        "Second consumption must fail with TokenAlreadyConsumed"
    );
}
