use hermes_session_rpc::{MessageRole, SessionManager, SessionState, SubmitStatus};

#[test]
fn test_session_create_and_idempotency() {
    let mut manager = SessionManager::new();
    let s1 = manager.create_session("profile-default", Some("idem-key-1"), Some("Chat A"));
    let s2 = manager.create_session("profile-default", Some("idem-key-1"), Some("Chat A duplicate"));

    // Idempotent creation returns the same session ID
    assert_eq!(s1, s2);
    assert_eq!(manager.get_state(&s1, "profile-default").unwrap(), SessionState::Idle);
    assert_eq!(manager.get_submit_status(&s1, "profile-default").unwrap(), SubmitStatus::Idle);
}

#[test]
fn test_deterministic_session_flow_complete() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, Some("Flow Test"));

    // Submit prompt
    manager.submit_prompt(&sid, "profile-default", "Hello agent!", false).unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Connecting);
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::InFlight);

    // Delta chunks
    let c1 = manager.on_text_delta(&sid, "profile-default", 0, "Hello ").unwrap();
    assert_eq!(c1, "Hello ");
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Streaming);

    let c2 = manager.on_text_delta(&sid, "profile-default", 1, "world!").unwrap();
    assert_eq!(c2, "Hello world!");

    // Terminal completion
    let full = manager.on_message_complete(&sid, "profile-default", "stop").unwrap();
    assert_eq!(full, "Hello world!");
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Idle);
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::Completed);

    // Verify authoritative history appending
    let history = manager.get_history(&sid, "profile-default").unwrap();
    assert_eq!(history.len(), 2);
    assert_eq!(history[0].role, MessageRole::User);
    assert_eq!(history[0].content, "Hello agent!");
    assert_eq!(history[1].role, MessageRole::Assistant);
    assert_eq!(history[1].content, "Hello world!");
}
