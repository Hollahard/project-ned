use hermes_session_rpc::{SessionManager, SessionRpcError, SessionState, SubmitStatus};

#[test]
fn test_transport_ambiguity_fencing_rejects_auto_replay() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, None);

    // Initial prompt submit
    manager.submit_prompt(&sid, "profile-default", "Run critical calculation", false).unwrap();
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::InFlight);

    // Transport network drop occurs mid-flight
    manager.on_network_drop(&sid, "profile-default").unwrap();
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::Uncertain);
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Idle);

    // Defense 1: Automatic replay (e.g. from network reconnection loop) is rejected
    let auto_replay_res = manager.submit_prompt(&sid, "profile-default", "Run critical calculation", false);
    assert!(auto_replay_res.is_err());
    match auto_replay_res.unwrap_err() {
        SessionRpcError::UncertainSubmitRequiresManualRetry(s) => assert_eq!(s, sid),
        other => panic!("Expected UncertainSubmitRequiresManualRetry, got: {:?}", other),
    }

    // Still in uncertain status
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::Uncertain);

    // Defense 2: Explicit manual retry succeeds and clears the ambiguity fence
    let manual_retry_res = manager.submit_prompt(&sid, "profile-default", "Run critical calculation", true);
    assert!(manual_retry_res.is_ok());
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::InFlight);
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Connecting);
}
