use hermes_session_rpc::{MessageRole, SessionManager, SessionState, ToolCall};

#[test]
fn test_state_transitions_with_tool_call_loop() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, Some("Tool Test"));

    // 1. Idle -> Connecting
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Idle);
    manager.submit_prompt(&sid, "profile-default", "Check files", false).unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Connecting);

    // 2. Connecting -> Streaming
    manager.on_text_delta(&sid, "profile-default", 0, "Checking... ").unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Streaming);

    // 3. Streaming -> AwaitingTool
    let tool = ToolCall {
        id: "call-123".to_string(),
        name: "list_files".to_string(),
        arguments: r#"{"path":"."}"#.to_string(),
    };
    manager.on_tool_call(&sid, "profile-default", tool).unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::AwaitingTool);

    // Prompt submit while awaiting tool is rejected with SessionBusy
    assert!(manager.submit_prompt(&sid, "profile-default", "Another prompt", false).is_err());

    // 4. AwaitingTool -> Streaming (Tool output provided)
    manager.on_tool_result(&sid, "profile-default", "call-123", "cargo.toml, src/").unwrap();
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Streaming);

    // Delta after tool execution
    manager.on_text_delta(&sid, "profile-default", 1, "Done listing.").unwrap();

    // 5. Streaming -> Idle (Complete)
    let full = manager.on_message_complete(&sid, "profile-default", "stop").unwrap();
    assert_eq!(full, "Checking... Done listing.");
    assert_eq!(manager.get_state(&sid, "profile-default").unwrap(), SessionState::Idle);

    // Authoritative history includes user, tool invocation, tool output, and final assistant message
    let history = manager.get_history(&sid, "profile-default").unwrap();
    assert_eq!(history.len(), 4);
    assert_eq!(history[0].role, MessageRole::User);
    assert_eq!(history[1].role, MessageRole::Assistant);
    assert!(history[1].tool_calls.is_some());
    assert_eq!(history[2].role, MessageRole::Tool);
    assert_eq!(history[2].tool_call_id.as_deref(), Some("call-123"));
    assert_eq!(history[3].role, MessageRole::Assistant);
    assert_eq!(history[3].content, "Checking... Done listing.");
}

#[test]
fn test_ordered_chunk_assembly_out_of_order_resolution() {
    let mut manager = SessionManager::new();
    let sid = manager.create_session("profile-default", None, None);
    manager.submit_prompt(&sid, "profile-default", "Question", false).unwrap();

    // Push chunk 1 before chunk 0
    let c1 = manager.on_text_delta(&sid, "profile-default", 1, "world").unwrap();
    assert_eq!(c1, ""); // Chunk 0 has not arrived yet, cannot assemble chunk 1

    // Push chunk 0
    let c0 = manager.on_text_delta(&sid, "profile-default", 0, "Hello ").unwrap();
    assert_eq!(c0, "Hello world"); // Now both 0 and 1 are drained in order!

    // Push chunk 2
    let c2 = manager.on_text_delta(&sid, "profile-default", 2, "!").unwrap();
    assert_eq!(c2, "Hello world!");
}
