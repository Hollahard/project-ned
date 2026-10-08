use crate::{remaining, HttpError, Limits, Response};
use std::collections::BTreeSet;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Instant;

pub(crate) fn write_request(
    stream: &mut TcpStream,
    mut bytes: &[u8],
    deadline: Instant,
) -> Result<(), HttpError> {
    while !bytes.is_empty() {
        stream
            .set_write_timeout(Some(remaining(deadline)?))
            .map_err(|_| HttpError("HTTP_SOCKET_CONFIG"))?;
        let n = stream.write(bytes).map_err(|_| io_error(deadline))?;
        if n == 0 {
            return Err(HttpError("HTTP_WRITE_FAILED"));
        }
        bytes = &bytes[n..];
    }
    remaining(deadline)?;
    Ok(())
}

struct Reader<'a> {
    stream: &'a mut TcpStream,
    deadline: Instant,
    buffer: [u8; 8192],
    offset: usize,
    filled: usize,
}
impl Reader<'_> {
    fn byte(&mut self) -> Result<Option<u8>, HttpError> {
        remaining(self.deadline)?;
        if self.offset == self.filled {
            self.stream
                .set_read_timeout(Some(remaining(self.deadline)?))
                .map_err(|_| HttpError("HTTP_SOCKET_CONFIG"))?;
            self.filled = self
                .stream
                .read(&mut self.buffer)
                .map_err(|_| io_error(self.deadline))?;
            self.offset = 0;
            if self.filled == 0 {
                return Ok(None);
            }
        }
        let value = self.buffer[self.offset];
        self.offset += 1;
        Ok(Some(value))
    }
    fn line(&mut self, cap: usize) -> Result<Vec<u8>, HttpError> {
        let mut line = Vec::new();
        loop {
            if line.len() >= cap {
                return Err(HttpError("HTTP_HEADER_LIMIT"));
            }
            let byte = self.byte()?.ok_or(HttpError("HTTP_TRUNCATED"))?;
            line.push(byte);
            if byte == b'\n' {
                if !line.ends_with(b"\r\n") {
                    return Err(HttpError("HTTP_MALFORMED"));
                }
                line.truncate(line.len() - 2);
                return Ok(line);
            }
        }
    }
    fn exact(&mut self, size: usize, body: &mut Vec<u8>) -> Result<(), HttpError> {
        for _ in 0..size {
            body.push(self.byte()?.ok_or(HttpError("HTTP_TRUNCATED"))?);
        }
        Ok(())
    }
    fn eof(&mut self) -> Result<(), HttpError> {
        if self.byte()?.is_some() {
            Err(HttpError("HTTP_TRAILING_BYTES"))
        } else {
            Ok(())
        }
    }
}

fn io_error(deadline: Instant) -> HttpError {
    if Instant::now() >= deadline {
        HttpError("HTTP_DEADLINE")
    } else {
        HttpError("HTTP_IO_FAILED")
    }
}

pub(crate) fn read_response(
    stream: &mut TcpStream,
    limits: Limits,
    deadline: Instant,
) -> Result<Response, HttpError> {
    let mut input = Reader {
        stream,
        deadline,
        buffer: [0; 8192],
        offset: 0,
        filled: 0,
    };
    let status = input.line(limits.max_header_bytes)?;
    let mut header_bytes = status.len() + 2;
    if status.len() < 12
        || !matches!(&status[..8], b"HTTP/1.1" | b"HTTP/1.0")
        || status[8] != b' '
        || !status[9..12].iter().all(u8::is_ascii_digit)
        || (status.len() > 12 && status[12] != b' ')
        || !status.iter().all(|b| (0x20..=0x7e).contains(b))
    {
        return Err(HttpError("HTTP_MALFORMED"));
    }
    let code = ((status[9] - b'0') as u16) * 100
        + ((status[10] - b'0') as u16) * 10
        + (status[11] - b'0') as u16;
    if !(200..=599).contains(&code) {
        return Err(HttpError("HTTP_STATUS_DENIED"));
    }
    if (300..=399).contains(&code) {
        return Err(HttpError("HTTP_REDIRECT_DENIED"));
    }
    let mut names = BTreeSet::new();
    let mut length = None;
    let mut chunked = false;
    loop {
        let line = input.line(limits.max_header_bytes.saturating_sub(header_bytes))?;
        header_bytes += line.len() + 2;
        if line.is_empty() {
            break;
        }
        if names.len() >= 128 {
            return Err(HttpError("HTTP_HEADER_LIMIT"));
        }
        let colon = line
            .iter()
            .position(|b| *b == b':')
            .ok_or(HttpError("HTTP_MALFORMED"))?;
        if colon == 0
            || !line[..colon]
                .iter()
                .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(b))
            || !line[colon + 1..]
                .iter()
                .all(|b| *b == b'\t' || (0x20..=0x7e).contains(b))
        {
            return Err(HttpError("HTTP_MALFORMED"));
        }
        let name: Vec<_> = line[..colon].iter().map(u8::to_ascii_lowercase).collect();
        if !names.insert(name.clone()) {
            return Err(HttpError("HTTP_DUPLICATE_HEADER"));
        }
        let value = std::str::from_utf8(&line[colon + 1..])
            .map_err(|_| HttpError("HTTP_MALFORMED"))?
            .trim_matches([' ', '\t']);
        match name.as_slice() {
            b"content-length" => {
                if value.is_empty()
                    || value.len() > 10
                    || !value.bytes().all(|b| b.is_ascii_digit())
                {
                    return Err(HttpError("HTTP_MALFORMED"));
                }
                let count: usize = value.parse().map_err(|_| HttpError("HTTP_BODY_LIMIT"))?;
                if count > limits.max_body_bytes {
                    return Err(HttpError("HTTP_BODY_LIMIT"));
                }
                length = Some(count);
            }
            b"transfer-encoding" => {
                if !value.eq_ignore_ascii_case("chunked") {
                    return Err(HttpError("HTTP_ENCODING_DENIED"));
                }
                chunked = true;
            }
            b"content-encoding" if !value.eq_ignore_ascii_case("identity") => {
                return Err(HttpError("HTTP_ENCODING_DENIED"))
            }
            _ => {}
        }
    }
    if chunked && length.is_some() {
        return Err(HttpError("HTTP_AMBIGUOUS_FRAMING"));
    }
    let mut body = Vec::new();
    if code == 204 || code == 304 {
        if chunked || length.is_some_and(|n| n != 0) {
            return Err(HttpError("HTTP_MALFORMED"));
        }
        input.eof()?;
    } else if chunked {
        let mut framing_bytes = 0;
        loop {
            let line = input.line(128)?;
            framing_bytes += line.len() + 2;
            if framing_bytes > limits.max_header_bytes {
                return Err(HttpError("HTTP_HEADER_LIMIT"));
            }
            if line.is_empty() || line.len() > 8 || !line.iter().all(u8::is_ascii_hexdigit) {
                return Err(HttpError("HTTP_MALFORMED"));
            }
            let count = usize::from_str_radix(
                std::str::from_utf8(&line).map_err(|_| HttpError("HTTP_MALFORMED"))?,
                16,
            )
            .map_err(|_| HttpError("HTTP_BODY_LIMIT"))?;
            if count > limits.max_body_bytes - body.len() {
                return Err(HttpError("HTTP_BODY_LIMIT"));
            }
            if count == 0 {
                // Diagnostic subset deliberately rejects chunk extensions and
                // trailers instead of giving them ambiguous interpretation.
                if !input.line(2)?.is_empty() {
                    return Err(HttpError("HTTP_MALFORMED"));
                }
                input.eof()?;
                break;
            }
            input.exact(count, &mut body)?;
            if !input.line(2)?.is_empty() {
                return Err(HttpError("HTTP_MALFORMED"));
            }
            framing_bytes += 2;
        }
    } else if let Some(count) = length {
        input.exact(count, &mut body)?;
        input.eof()?;
    } else {
        while let Some(byte) = input.byte()? {
            if body.len() == limits.max_body_bytes {
                return Err(HttpError("HTTP_BODY_LIMIT"));
            }
            body.push(byte);
        }
    }
    remaining(deadline)?;
    Ok(Response { status: code, body })
}
