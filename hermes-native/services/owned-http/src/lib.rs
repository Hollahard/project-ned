//! Diagnostic-only loopback HTTP. No renderer API, redirects, proxies or retries.
#![cfg(windows)]

mod http;
mod ownership;

use hermes_resource_host::WorkerGroup;
use std::fmt;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug)]
pub struct Limits {
    /// One absolute budget for connect, ownership, write, headers and body.
    pub timeout: Duration,
    pub max_header_bytes: usize,
    pub max_body_bytes: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(15),
            max_header_bytes: 16 * 1024,
            max_body_bytes: 1024 * 1024,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Method {
    Get,
    Post,
}

/// Static diagnostic errors cannot accidentally disclose headers or payloads.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HttpError(&'static str);
impl HttpError {
    pub fn code(&self) -> &'static str {
        self.0
    }
}
impl fmt::Display for HttpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for HttpError {}

/// Intentionally no Debug/Serialize: callers explicitly inspect bounded bytes.
pub struct Response {
    status: u16,
    body: Vec<u8>,
}
impl Response {
    pub fn status_code(&self) -> u16 {
        self.status
    }
    pub fn body(&self) -> &[u8] {
        &self.body
    }
}

pub struct OwnedHttpClient<'a> {
    group: &'a WorkerGroup,
    port: u16,
    limits: Limits,
}
impl<'a> OwnedHttpClient<'a> {
    pub fn new(group: &'a WorkerGroup, port: u16, limits: Limits) -> Result<Self, HttpError> {
        if port == 0
            || limits.timeout.is_zero()
            || limits.timeout > Duration::from_secs(30)
            || !(128..=65536).contains(&limits.max_header_bytes)
            || limits.max_body_bytes == 0
            || limits.max_body_bytes > 1024 * 1024
        {
            return Err(HttpError("HTTP_INVALID_LIMITS"));
        }
        Ok(Self {
            group,
            port,
            limits,
        })
    }

    /// Only the finite retained-backend proof contract is allowed. At most two
    /// session-token headers intentionally permit the duplicate-auth rejection
    /// test. The sole POST body is `{}` on /api/config (expected forbidden).
    pub fn request(
        &self,
        method: Method,
        path: &str,
        headers: &[(&str, &str)],
        body: Option<&[u8]>,
    ) -> Result<Response, HttpError> {
        validate_request(method, path, headers, body)?;
        let deadline = Instant::now() + self.limits.timeout;
        let address = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, self.port));
        let mut stream = TcpStream::connect_timeout(&address, remaining(deadline)?)
            .map_err(|_| HttpError("HTTP_CONNECT_FAILED"))?;
        // A TCP handshake contains no application bytes. Validate the actual
        // connected socket, never a listener-port lookup, before serializing or
        // transmitting any credential-bearing HTTP request.
        ownership::verify(&stream, self.group)?;
        remaining(deadline)?;
        let mut request = format!("{} {path} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\nAccept: application/json\r\n", if method == Method::Get { "GET" } else { "POST" }, self.port).into_bytes();
        for (_, value) in headers {
            request.extend_from_slice(b"X-Hermes-Session-Token: ");
            request.extend_from_slice(value.as_bytes());
            request.extend_from_slice(b"\r\n");
        }
        if let Some(body) = body {
            request
                .extend_from_slice(b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n");
            request.extend_from_slice(body);
        } else {
            request.extend_from_slice(b"\r\n");
        }
        http::write_request(&mut stream, &request, deadline)?;
        http::read_response(&mut stream, self.limits, deadline)
    }
}

fn validate_request(
    method: Method,
    path: &str,
    headers: &[(&str, &str)],
    body: Option<&[u8]>,
) -> Result<(), HttpError> {
    const PATHS: &[&str] = &[
        "/api/config",
        "/api/config?include_defaults=invalid",
        "/api/config?profile=default",
        "/api/sessions?limit=20&order=recent",
        "/api/sessions?order=invalid",
        "/api/sessions?limit=101",
        "/diagnostic/identity",
        "/api/env",
    ];
    if !PATHS.contains(&path)
        || headers.len() > 2
        || headers.iter().any(|(name, value)| {
            !name.eq_ignore_ascii_case("X-Hermes-Session-Token")
                || value.is_empty()
                || value.len() > 512
                || !value.bytes().all(|b| (0x21..=0x7e).contains(&b))
        })
        || match method {
            Method::Get => body.is_some(),
            Method::Post => path != "/api/config" || body != Some(b"{}"),
        }
    {
        return Err(HttpError("HTTP_REQUEST_DENIED"));
    }
    Ok(())
}

fn remaining(deadline: Instant) -> Result<Duration, HttpError> {
    let left = deadline.saturating_duration_since(Instant::now());
    if left.is_zero() {
        Err(HttpError("HTTP_DEADLINE"))
    } else {
        Ok(left)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn request_contract_is_finite_and_header_injection_is_rejected() {
        assert!(validate_request(Method::Get, "/api/config", &[], None).is_ok());
        assert!(validate_request(
            Method::Get,
            "/api/env",
            &[("X-Hermes-Session-Token", "canary")],
            None
        )
        .is_ok());
        for path in [
            "http://example.com/",
            "/api/config\r\nX: y",
            "/health",
            "/api/config?unknown=1",
        ] {
            assert!(validate_request(Method::Get, path, &[], None).is_err());
        }
        assert!(validate_request(
            Method::Get,
            "/api/config",
            &[("Authorization", "secret")],
            None
        )
        .is_err());
        assert!(validate_request(
            Method::Get,
            "/api/config",
            &[("X-Hermes-Session-Token", "x\r\nx")],
            None
        )
        .is_err());
        assert!(validate_request(Method::Post, "/api/config", &[], Some(b"{}")).is_ok());
        assert!(
            validate_request(Method::Post, "/api/config", &[], Some(b"{\"secret\":1}")).is_err()
        );
    }
}
