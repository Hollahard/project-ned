//! Bounded local WebSocket transport tied to a private Windows Job.
#![cfg(windows)]
mod stream;
use hermes_resource_host::WorkerGroup;
use std::fmt;
use std::net::Shutdown;
use std::time::{Duration, Instant};
use stream::DeadlineStream;
use tungstenite::{protocol::WebSocketConfig, Message, WebSocket};
#[derive(Clone, Copy, Debug)]
pub struct Limits {
    pub connect_timeout: Duration,
    pub operation_timeout: Duration,
    pub close_timeout: Duration,
    pub max_header_bytes: usize,
    pub max_message_bytes: usize,
    pub max_frame_bytes: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            connect_timeout: Duration::from_secs(5),
            operation_timeout: Duration::from_secs(15),
            close_timeout: Duration::from_secs(2),
            max_header_bytes: 16384,
            max_message_bytes: 1048576,
            max_frame_bytes: 262144,
        }
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WsError(&'static str);
impl WsError {
    pub fn code(self) -> &'static str {
        self.0
    }
}
impl fmt::Display for WsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for WsError {}
/// Deliberately no Debug/Serialize: callers choose how to handle bounded data.
pub enum Event {
    Text(String),
    Binary(Vec<u8>),
    Ping(Vec<u8>),
    Pong(Vec<u8>),
    Close { code: Option<u16> },
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CloseReport {
    pub peer_close_observed: bool,
    pub connection_closed: bool,
}
pub struct OwnedWebSocket<'a> {
    socket: WebSocket<DeadlineStream<'a>>,
    limits: Limits,
    closed: bool,
    peer_close: bool,
}
impl<'a> OwnedWebSocket<'a> {
    pub fn connect(
        group: &'a WorkerGroup,
        port: u16,
        token: &str,
        limits: Limits,
    ) -> Result<Self, WsError> {
        validate(limits, token)?;
        let deadline = Instant::now() + limits.connect_timeout;
        let tcp = hermes_owned_http::connect_owned(group, port, left(deadline)?)
            .map_err(|_| WsError("WS_OWNER_OR_CONNECT_FAILED"))?;
        let pid = hermes_owned_http::observed_owned_peer_pid(&tcp, group)
            .map_err(|_| WsError("WS_OWNER_OR_CONNECT_FAILED"))?;
        // No URL helper may create a second socket. Credential-bearing target is
        // constructed only after the exact connected tuple has passed ownership.
        let request = tungstenite::http::Request::builder()
            .method("GET")
            .uri(format!("ws://127.0.0.1:{port}/api/ws?token={token}"))
            .header("Host", format!("127.0.0.1:{port}"))
            .header("Connection", "Upgrade")
            .header("Upgrade", "websocket")
            .header("Sec-WebSocket-Version", "13")
            .header(
                "Sec-WebSocket-Key",
                tungstenite::handshake::client::generate_key(),
            )
            .header("Origin", format!("http://127.0.0.1:{port}"))
            .body(())
            .map_err(|_| WsError("WS_REQUEST_INVALID"))?;
        let stream = DeadlineStream::new(tcp, group, pid, deadline, limits.max_header_bytes);
        let config = WebSocketConfig::default()
            .read_buffer_size(4096)
            .write_buffer_size(0)
            .max_write_buffer_size(limits.max_message_bytes + 4096)
            .max_message_size(Some(limits.max_message_bytes))
            .max_frame_size(Some(limits.max_frame_bytes));
        let (mut socket, response) =
            tungstenite::client::client_with_config(request, stream, Some(config))
                .map_err(|_| WsError("WS_UPGRADE_FAILED"))?;
        if response.headers().contains_key("sec-websocket-protocol")
            || response.headers().contains_key("sec-websocket-extensions")
            || response.headers().len() > 32
            || ["upgrade", "connection", "sec-websocket-accept"]
                .iter()
                .any(|key| response.headers().get_all(*key).iter().count() != 1)
        {
            let _ = socket.get_ref().tcp.shutdown(Shutdown::Both);
            return Err(WsError("WS_UPGRADE_FAILED"));
        }
        left(deadline)?;
        socket.get_mut().finish_handshake();
        Ok(Self {
            socket,
            limits,
            closed: false,
            peer_close: false,
        })
    }
    pub fn send_text(&mut self, text: &str) -> Result<(), WsError> {
        if text.len() > self.limits.max_message_bytes {
            return Err(WsError("WS_MESSAGE_LIMIT"));
        }
        self.begin(self.limits.operation_timeout)?;
        let result = self.socket.send(Message::Text(text.to_owned().into()));
        self.finish(result)
    }
    pub fn send_binary(&mut self, bytes: &[u8]) -> Result<(), WsError> {
        if bytes.len() > self.limits.max_message_bytes {
            return Err(WsError("WS_MESSAGE_LIMIT"));
        }
        self.begin(self.limits.operation_timeout)?;
        let result = self.socket.send(Message::Binary(bytes.to_owned().into()));
        self.finish(result)
    }
    pub fn read(&mut self) -> Result<Event, WsError> {
        self.begin(self.limits.operation_timeout)?;
        let result = self.socket.read();
        let message = self.finish(result)?;
        let event = match message {
            Message::Text(text) => Event::Text(text.to_string()),
            Message::Binary(data) => Event::Binary(data.to_vec()),
            Message::Ping(data) => {
                let result = self.socket.flush();
                self.finish(result)?;
                Event::Ping(data.to_vec())
            }
            Message::Pong(data) => Event::Pong(data.to_vec()),
            Message::Close(close) => {
                self.peer_close = true;
                let result = self.socket.flush();
                self.finish(result)?;
                Event::Close {
                    code: close.map(|c| c.code.into()),
                }
            }
            Message::Frame(_) => {
                self.abort();
                return Err(WsError("WS_PROTOCOL_FAILED"));
            }
        };
        Ok(event)
    }
    /// Completes a bounded close exchange; a timeout/EOF without the protocol
    /// close is an error and permanently closes this transport, never success.
    pub fn close(&mut self) -> Result<CloseReport, WsError> {
        self.begin(self.limits.close_timeout)?;
        if !self.peer_close {
            let result = self.socket.close(None);
            self.finish(result)?;
        }
        loop {
            match self.socket.read() {
                Ok(Message::Close(_)) => self.peer_close = true,
                Ok(_) => {}
                Err(tungstenite::Error::ConnectionClosed) => {
                    if self.socket.get_ref().check().is_err() {
                        self.abort();
                        return Err(WsError("WS_CLOSE_INCOMPLETE"));
                    }
                    self.closed = true;
                    let _ = self.socket.get_ref().tcp.shutdown(Shutdown::Both);
                    return if self.peer_close {
                        Ok(CloseReport {
                            peer_close_observed: true,
                            connection_closed: true,
                        })
                    } else {
                        Err(WsError("WS_CLOSE_INCOMPLETE"))
                    };
                }
                Err(_) => {
                    self.abort();
                    return Err(WsError("WS_CLOSE_INCOMPLETE"));
                }
            }
            if self.socket.get_ref().check().is_err() {
                self.abort();
                return Err(WsError("WS_CLOSE_INCOMPLETE"));
            }
        }
    }
    pub fn abort(&mut self) {
        self.closed = true;
        let _ = self.socket.get_ref().tcp.shutdown(Shutdown::Both);
    }
    fn begin(&mut self, timeout: Duration) -> Result<(), WsError> {
        if self.closed {
            return Err(WsError("WS_CLOSED"));
        }
        self.socket.get_mut().reset(Instant::now() + timeout);
        if self.socket.get_ref().check().is_err() {
            self.abort();
            return Err(WsError("WS_OWNER_OR_DEADLINE"));
        }
        Ok(())
    }
    fn finish<T>(&mut self, result: Result<T, tungstenite::Error>) -> Result<T, WsError> {
        match result {
            Ok(value) => {
                if self.socket.get_ref().check().is_ok() {
                    Ok(value)
                } else {
                    self.abort();
                    Err(WsError("WS_OWNER_OR_DEADLINE"))
                }
            }
            Err(_) => {
                self.abort();
                Err(WsError("WS_TRANSPORT_OR_PROTOCOL"))
            }
        }
    }
}
impl Drop for OwnedWebSocket<'_> {
    fn drop(&mut self) {
        self.abort();
    }
}
fn left(deadline: Instant) -> Result<Duration, WsError> {
    let duration = deadline.saturating_duration_since(Instant::now());
    if duration.is_zero() {
        Err(WsError("WS_DEADLINE"))
    } else {
        Ok(duration)
    }
}
fn validate(limits: Limits, token: &str) -> Result<(), WsError> {
    if token.is_empty()
        || token.len() > 512
        || !token
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-._~".contains(&b))
        || limits.connect_timeout.is_zero()
        || limits.connect_timeout > Duration::from_secs(30)
        || limits.operation_timeout.is_zero()
        || limits.operation_timeout > Duration::from_secs(30)
        || limits.close_timeout.is_zero()
        || limits.close_timeout > Duration::from_secs(5)
        || !(256..=65536).contains(&limits.max_header_bytes)
        || !(1..=1048576).contains(&limits.max_message_bytes)
        || !(1..=1048576).contains(&limits.max_frame_bytes)
        || limits.max_frame_bytes > limits.max_message_bytes
    {
        return Err(WsError("WS_INVALID_INPUT"));
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn credentials_and_hard_bounds_are_finite() {
        for token in ["", "a&other=x", "a/b", "a\r\nb", "token%20"] {
            assert!(validate(Limits::default(), token).is_err());
        }
        assert!(validate(Limits::default(), "canary-1_.~").is_ok());
        let limits = Limits {
            max_message_bytes: 1048577,
            ..Limits::default()
        };
        assert!(validate(limits, "x").is_err());
    }
}
