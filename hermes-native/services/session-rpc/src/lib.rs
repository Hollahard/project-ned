//! Hermes native session RPC state machine, streaming delta assembly,
//! and transport ambiguity fencing.

use std::collections::HashMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SessionState {
    Idle,
    Connecting,
    Streaming,
    AwaitingTool,
    Interrupted,
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SubmitStatus {
    Idle,
    InFlight,
    Uncertain,
    Completed,
    Interrupted,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MessageRole {
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Message {
    pub role: MessageRole,
    pub content: String,
    pub tool_calls: Option<Vec<ToolCall>>,
    pub tool_call_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum StreamingDelta {
    Text { chunk_index: usize, text: String },
    Tool { tool_call: ToolCall },
    Complete { finish_reason: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SessionRpcError {
    SessionNotFound(String),
    ProfileMismatch { session_id: String, expected_profile: String, actual_profile: String },
    SessionBusy(String),
    UncertainSubmitRequiresManualRetry(String),
    InvalidChunkSequence { expected: usize, received: usize },
    InvalidStateTransition { current: SessionState, attempted: &'static str },
    ToolCallNotFound(String),
}

impl std::fmt::Display for SessionRpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::SessionNotFound(id) => write!(f, "Session '{}' not found", id),
            Self::ProfileMismatch { session_id, expected_profile, actual_profile } => {
                write!(f, "Profile mismatch for session '{}': session belongs to '{}', received request from '{}'", session_id, expected_profile, actual_profile)
            }
            Self::SessionBusy(id) => write!(f, "Session '{}' is busy executing a prompt", id),
            Self::UncertainSubmitRequiresManualRetry(id) => {
                write!(f, "Session '{}' is in UNCERTAIN state due to transport disruption. Automatic retry is strictly prohibited; manual re-submission is required.", id)
            }
            Self::InvalidChunkSequence { expected, received } => {
                write!(f, "Invalid chunk sequence: expected index {}, received {}", expected, received)
            }
            Self::InvalidStateTransition { current, attempted } => {
                write!(f, "Invalid state transition from {:?} via {}", current, attempted)
            }
            Self::ToolCallNotFound(id) => write!(f, "Pending tool call '{}' not found", id),
        }
    }
}

impl std::error::Error for SessionRpcError {}

#[derive(Debug, Clone, Default)]
pub struct ChunkAssembler {
    expected_index: usize,
    assembled_text: String,
    buffer: HashMap<usize, String>,
}

impl ChunkAssembler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push_chunk(&mut self, index: usize, text: &str) -> Result<String, SessionRpcError> {
        if index < self.expected_index {
            // Duplicate chunk, ignore
            return Ok(self.assembled_text.clone());
        }

        self.buffer.insert(index, text.to_string());

        // Drain consecutive chunks starting from expected_index
        while let Some(chunk) = self.buffer.remove(&self.expected_index) {
            self.assembled_text.push_str(&chunk);
            self.expected_index += 1;
        }

        Ok(self.assembled_text.clone())
    }

    pub fn current_text(&self) -> &str {
        &self.assembled_text
    }

    pub fn is_complete(&self) -> bool {
        self.buffer.is_empty()
    }

    pub fn reset(&mut self) {
        self.expected_index = 0;
        self.assembled_text.clear();
        self.buffer.clear();
    }
}

#[derive(Debug, Clone)]
pub struct SessionRecord {
    pub session_id: String,
    pub profile_id: String,
    pub title: String,
    pub state: SessionState,
    pub submit_status: SubmitStatus,
    pub history: Vec<Message>,
    pub assembler: ChunkAssembler,
    pub pending_tool_calls: Vec<ToolCall>,
    pub uncertain_latch: bool,
}

#[derive(Debug, Clone, Default)]
pub struct SessionManager {
    sessions: HashMap<String, SessionRecord>,
    idempotency_map: HashMap<String, String>,
    next_id: usize,
}

impl SessionManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn create_session(
        &mut self,
        profile_id: &str,
        idempotency_key: Option<&str>,
        title: Option<&str>,
    ) -> String {
        if let Some(key) = idempotency_key {
            if let Some(existing_id) = self.idempotency_map.get(key) {
                return existing_id.clone();
            }
        }

        self.next_id += 1;
        let session_id = format!("sess-{}-{}", profile_id, self.next_id);
        let session_title = title.unwrap_or("Untitled Session").to_string();

        let record = SessionRecord {
            session_id: session_id.clone(),
            profile_id: profile_id.to_string(),
            title: session_title,
            state: SessionState::Idle,
            submit_status: SubmitStatus::Idle,
            history: Vec::new(),
            assembler: ChunkAssembler::new(),
            pending_tool_calls: Vec::new(),
            uncertain_latch: false,
        };

        self.sessions.insert(session_id.clone(), record);
        if let Some(key) = idempotency_key {
            self.idempotency_map.insert(key.to_string(), session_id.clone());
        }

        session_id
    }

    fn get_session_mut(&mut self, session_id: &str, profile_id: &str) -> Result<&mut SessionRecord, SessionRpcError> {
        let record = self.sessions.get_mut(session_id).ok_or_else(|| {
            SessionRpcError::SessionNotFound(session_id.to_string())
        })?;

        if record.profile_id != profile_id {
            return Err(SessionRpcError::ProfileMismatch {
                session_id: session_id.to_string(),
                expected_profile: record.profile_id.clone(),
                actual_profile: profile_id.to_string(),
            });
        }

        Ok(record)
    }

    pub fn submit_prompt(
        &mut self,
        session_id: &str,
        profile_id: &str,
        text: &str,
        is_manual_retry: bool,
    ) -> Result<(), SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        // Uncertain-Submit Defense: Transport ambiguity fencing
        if session.uncertain_latch && !is_manual_retry {
            return Err(SessionRpcError::UncertainSubmitRequiresManualRetry(session_id.to_string()));
        }

        match session.state {
            SessionState::Connecting | SessionState::Streaming | SessionState::AwaitingTool => {
                return Err(SessionRpcError::SessionBusy(session_id.to_string()));
            }
            _ => {}
        }

        session.uncertain_latch = false;
        session.state = SessionState::Connecting;
        session.submit_status = SubmitStatus::InFlight;
        session.assembler.reset();
        session.pending_tool_calls.clear();

        session.history.push(Message {
            role: MessageRole::User,
            content: text.to_string(),
            tool_calls: None,
            tool_call_id: None,
        });

        Ok(())
    }

    pub fn on_network_drop(&mut self, session_id: &str, profile_id: &str) -> Result<(), SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        // If submit was in flight, transition to Uncertain
        if session.submit_status == SubmitStatus::InFlight {
            session.submit_status = SubmitStatus::Uncertain;
            session.uncertain_latch = true;
            session.state = SessionState::Idle;
        }

        Ok(())
    }

    pub fn on_text_delta(
        &mut self,
        session_id: &str,
        profile_id: &str,
        chunk_index: usize,
        text: &str,
    ) -> Result<String, SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        match session.state {
            SessionState::Connecting | SessionState::Streaming => {
                session.state = SessionState::Streaming;
            }
            state => {
                return Err(SessionRpcError::InvalidStateTransition {
                    current: state,
                    attempted: "on_text_delta",
                });
            }
        }

        session.assembler.push_chunk(chunk_index, text)
    }

    pub fn on_tool_call(
        &mut self,
        session_id: &str,
        profile_id: &str,
        tool_call: ToolCall,
    ) -> Result<(), SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        match session.state {
            SessionState::Connecting | SessionState::Streaming => {
                session.state = SessionState::AwaitingTool;
                session.pending_tool_calls.push(tool_call);
                Ok(())
            }
            state => Err(SessionRpcError::InvalidStateTransition {
                current: state,
                attempted: "on_tool_call",
            }),
        }
    }

    pub fn on_tool_result(
        &mut self,
        session_id: &str,
        profile_id: &str,
        tool_call_id: &str,
        output: &str,
    ) -> Result<(), SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        if session.state != SessionState::AwaitingTool {
            return Err(SessionRpcError::InvalidStateTransition {
                current: session.state,
                attempted: "on_tool_result",
            });
        }

        let idx = session
            .pending_tool_calls
            .iter()
            .position(|t| t.id == tool_call_id)
            .ok_or_else(|| SessionRpcError::ToolCallNotFound(tool_call_id.to_string()))?;

        let call = session.pending_tool_calls.remove(idx);

        // Append assistant tool call invocation to history
        session.history.push(Message {
            role: MessageRole::Assistant,
            content: String::new(),
            tool_calls: Some(vec![call]),
            tool_call_id: None,
        });

        // Append tool result to history
        session.history.push(Message {
            role: MessageRole::Tool,
            content: output.to_string(),
            tool_calls: None,
            tool_call_id: Some(tool_call_id.to_string()),
        });

        if session.pending_tool_calls.is_empty() {
            session.state = SessionState::Streaming;
        }

        Ok(())
    }

    pub fn on_message_complete(
        &mut self,
        session_id: &str,
        profile_id: &str,
        finish_reason: &str,
    ) -> Result<String, SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        let full_text = session.assembler.current_text().to_string();

        if !full_text.is_empty() {
            session.history.push(Message {
                role: MessageRole::Assistant,
                content: full_text.clone(),
                tool_calls: None,
                tool_call_id: None,
            });
        }

        session.state = SessionState::Idle;
        session.submit_status = SubmitStatus::Completed;
        session.assembler.reset();
        session.pending_tool_calls.clear();

        let _ = finish_reason;
        Ok(full_text)
    }

    pub fn interrupt(
        &mut self,
        session_id: &str,
        profile_id: &str,
    ) -> Result<InterruptOutcome, SessionRpcError> {
        let session = self.get_session_mut(session_id, profile_id)?;

        match session.state {
            SessionState::Connecting | SessionState::Streaming | SessionState::AwaitingTool => {
                let cancelled_tools = session.pending_tool_calls.len();
                session.pending_tool_calls.clear();

                let partial_text = session.assembler.current_text().to_string();
                if !partial_text.is_empty() {
                    session.history.push(Message {
                        role: MessageRole::Assistant,
                        content: format!("{} [interrupted]", partial_text),
                        tool_calls: None,
                        tool_call_id: None,
                    });
                }

                session.state = SessionState::Idle;
                session.submit_status = SubmitStatus::Interrupted;
                session.assembler.reset();

                Ok(InterruptOutcome {
                    interrupted: true,
                    cancelled_tools,
                    partial_text,
                })
            }
            _ => Ok(InterruptOutcome {
                interrupted: false,
                cancelled_tools: 0,
                partial_text: String::new(),
            }),
        }
    }

    pub fn get_history(
        &self,
        session_id: &str,
        profile_id: &str,
    ) -> Result<&[Message], SessionRpcError> {
        let session = self.sessions.get(session_id).ok_or_else(|| {
            SessionRpcError::SessionNotFound(session_id.to_string())
        })?;

        if session.profile_id != profile_id {
            return Err(SessionRpcError::ProfileMismatch {
                session_id: session_id.to_string(),
                expected_profile: session.profile_id.clone(),
                actual_profile: profile_id.to_string(),
            });
        }

        Ok(&session.history)
    }

    pub fn get_state(&self, session_id: &str, profile_id: &str) -> Result<SessionState, SessionRpcError> {
        let session = self.sessions.get(session_id).ok_or_else(|| {
            SessionRpcError::SessionNotFound(session_id.to_string())
        })?;

        if session.profile_id != profile_id {
            return Err(SessionRpcError::ProfileMismatch {
                session_id: session_id.to_string(),
                expected_profile: session.profile_id.clone(),
                actual_profile: profile_id.to_string(),
            });
        }

        Ok(session.state)
    }

    pub fn get_submit_status(&self, session_id: &str, profile_id: &str) -> Result<SubmitStatus, SessionRpcError> {
        let session = self.sessions.get(session_id).ok_or_else(|| {
            SessionRpcError::SessionNotFound(session_id.to_string())
        })?;

        if session.profile_id != profile_id {
            return Err(SessionRpcError::ProfileMismatch {
                session_id: session_id.to_string(),
                expected_profile: session.profile_id.clone(),
                actual_profile: profile_id.to_string(),
            });
        }

        Ok(session.submit_status)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterruptOutcome {
    pub interrupted: bool,
    pub cancelled_tools: usize,
    pub partial_text: String,
}
