use hermes_session_rpc::{SessionManager, SessionRpcError};

#[test]
fn test_profile_fencing_prevents_cross_profile_leakage() {
    let mut manager = SessionManager::new();

    // Create session for Alice
    let sid_alice = manager.create_session("profile-alice", None, Some("Alice Confidential"));
    manager.submit_prompt(&sid_alice, "profile-alice", "Alice private key", false).unwrap();
    manager.on_text_delta(&sid_alice, "profile-alice", 0, "Top secret response").unwrap();
    manager.on_message_complete(&sid_alice, "profile-alice", "stop").unwrap();

    // 1. Bob attempts to read Alice's history -> REJECTED
    let bob_history = manager.get_history(&sid_alice, "profile-bob");
    assert!(bob_history.is_err());
    match bob_history.unwrap_err() {
        SessionRpcError::ProfileMismatch { expected_profile, actual_profile, .. } => {
            assert_eq!(expected_profile, "profile-alice");
            assert_eq!(actual_profile, "profile-bob");
        }
        other => panic!("Expected ProfileMismatch, got: {:?}", other),
    }

    // 2. Bob attempts to submit prompt into Alice's session -> REJECTED
    let bob_submit = manager.submit_prompt(&sid_alice, "profile-bob", "Bob injection", false);
    assert!(bob_submit.is_err());
    assert!(matches!(bob_submit.unwrap_err(), SessionRpcError::ProfileMismatch { .. }));

    // 3. Bob attempts to interrupt Alice's session -> REJECTED
    let bob_interrupt = manager.interrupt(&sid_alice, "profile-bob");
    assert!(bob_interrupt.is_err());
    assert!(matches!(bob_interrupt.unwrap_err(), SessionRpcError::ProfileMismatch { .. }));

    // 4. Alice can read her own history cleanly
    let alice_history = manager.get_history(&sid_alice, "profile-alice").unwrap();
    assert_eq!(alice_history.len(), 2);
    assert_eq!(alice_history[0].content, "Alice private key");
    assert_eq!(alice_history[1].content, "Top secret response");
}
