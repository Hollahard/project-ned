use hermes_session_rpc::{SessionManager, SessionState, SubmitStatus, ToolCall};

#[test]
fn test_session_interrupt_during_streaming() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, None);

    manager.submit_prompt(&sid, "profile-default", "Start long generation", false).unwrap();
    manager.on_text_delta(&sid, "profile-default", 0, "Partial output before cancel").unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Streaming);

    // Interrupt triggered
    let outcome = manager.interrupt(&sid, "profile-default").unwrap();
    assert!(outcome.interrupted);
    assert_eq!(outcome.partial_text, "Partial output before cancel");
    assert_eq!(outcome.cancelled_tools, 0);

    // State returns to Idle, submit status is Interrupted
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Idle);
    assert_eq!(manager.get_submit_status(&sid, "profile-default").unwrap(), SubmitStatus::Interrupted);

    // Subsequent interrupt on idle session returns not_interrupted
    let idle_outcome = manager.interrupt(&sid, "profile-default").unwrap();
    assert!(!idle_outcome.interrupted);
}

#[test]
fn test_session_interrupt_cancels_pending_tools() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, None);

    manager.submit_prompt(&sid, "profile-default", "Execute dangerous command", false).unwrap();
    manager.on_tool_call(&sid, "profile-default", ToolCall {
        id: "call-99".to_string(),
        name: "execute_shell".to_string(),
        arguments: "rm -rf".to_string(),
    }).unwrap();

    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::AwaitingTool);

    // Trigger interrupt
    let outcome = manager.interrupt(&sid, "profile-default").unwrap();
    assert!(outcome.interrupted);
    assert_eq!(outcome.cancelled_tools, 1);

    // Tool call is no longer pending
    let tool_res = manager.on_tool_result(&sid, "profile-default", "call-99", "result");
    assert!(tool_res.is_err());
}
