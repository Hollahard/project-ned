use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::time::Duration;
use tungstenite::{
    protocol::frame::{
        coding::{Data, OpCode},
        Frame,
    },
    Message,
};
const TOKEN: &str = "synthetic-token-canary-41";
struct Wire {
    tcp: TcpStream,
    count: usize,
    path: PathBuf,
    coalesce: bool,
    pending: Vec<u8>,
}
impl Read for Wire {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let n = self.tcp.read(buf)?;
        self.count += n;
        std::fs::write(&self.path, self.count.to_string())?;
        Ok(n)
    }
}
impl Write for Wire {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.coalesce {
            self.pending.extend_from_slice(buf);
            Ok(buf.len())
        } else {
            self.tcp.write(buf)
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        if self.coalesce {
            self.coalesce = false;
            Frame::message("coalesced-first", OpCode::Data(Data::Text), true)
                .format(&mut self.pending)
                .unwrap();
            self.tcp.write_all(&self.pending)?;
            self.pending.clear();
        }
        self.tcp.flush()
    }
}
// Callback error shape is fixed by the upstream handshake API.
#[allow(clippy::result_large_err)]
fn main() {
    let args: Vec<_> = std::env::args().collect();
    let mode = &args[1];
    let count = PathBuf::from(&args[2]);
    if mode == "descendant" {
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["echo", &args[2]])
            .spawn()
            .unwrap();
        let _ = child.wait();
        return;
    }
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    println!(
        "HERMES_BACKEND_READY port={}",
        listener.local_addr().unwrap().port()
    );
    std::io::stdout().flush().unwrap();
    for tcp in listener.incoming() {
        let tcp = tcp.unwrap();
        tcp.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
        tcp.set_write_timeout(Some(Duration::from_secs(3))).unwrap();
        let mut wire = Wire {
            tcp,
            count: 0,
            path: count.clone(),
            coalesce: mode == "coalesced",
            pending: Vec::new(),
        };
        if ["redirect", "hugeheaders", "slowupgrade"].contains(&mode.as_str()) {
            let mut request = Vec::new();
            let mut byte = [0u8; 1];
            while request.len() < 4096 && !request.ends_with(b"\r\n\r\n") {
                match wire.read(&mut byte) {
                    Ok(1) => request.push(byte[0]),
                    _ => break,
                }
            }
            if request.is_empty() {
                continue;
            }
            if mode == "redirect" {
                let _=wire.write_all(b"HTTP/1.1 302 Found\r\nLocation: ws://127.0.0.1:9/\r\nContent-Length: 0\r\n\r\n");
            }
            if mode == "hugeheaders" {
                let _ = wire.write_all(b"HTTP/1.1 101 Switching Protocols\r\nX: ");
                let _ = wire.write_all(&vec![b'x'; 20000]);
            }
            if mode == "slowupgrade" {
                for b in b"HTTP/1.1 101 Switching Protocols\r\nX: slow\r\n\r\n" {
                    if wire.write_all(&[*b]).is_err() {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(30));
                }
            }
            continue;
        }
        let callback =
            |request: &tungstenite::handshake::server::Request,
             mut response: tungstenite::handshake::server::Response| {
                if request.uri().path() != "/api/ws"
                    || request.uri().query() != Some(&format!("token={TOKEN}"))
                {
                    return Err(tungstenite::http::Response::builder()
                        .status(403)
                        .body(Some("Denied".into()))
                        .unwrap());
                }
                std::fs::write(count.with_extension("auth"), b"verified").unwrap();
                match mode.as_str() {
                    "extension" => {
                        response.headers_mut().insert(
                            "sec-websocket-extensions",
                            "permessage-deflate".parse().unwrap(),
                        );
                    }
                    "subprotocol" => {
                        response
                            .headers_mut()
                            .insert("sec-websocket-protocol", "unexpected".parse().unwrap());
                    }
                    "duplicate" => {
                        response
                            .headers_mut()
                            .append("sec-websocket-accept", "ambiguous".parse().unwrap());
                    }
                    _ => {}
                }
                Ok(response)
            };
        let Ok(mut ws) = tungstenite::accept_hdr(wire, callback) else {
            continue;
        };
        if mode == "noread" {
            std::thread::sleep(Duration::from_secs(2));
            continue;
        }
        if mode == "abrupt" {
            continue;
        }
        match mode.as_str() {
            "peerclose" => {
                let _ = ws.close(Some(tungstenite::protocol::CloseFrame {
                    code: tungstenite::protocol::frame::coding::CloseCode::Normal,
                    reason: "synthetic-close-canary".into(),
                }));
            }
            "controls" => {
                let _ = ws.send(Message::Ping("synthetic-ping-canary".into()));
                let _ = ws.send(Message::Pong("pong".into()));
                let _ = ws.send(Message::Frame(Frame::message(
                    "part-",
                    OpCode::Data(Data::Text),
                    false,
                )));
                let _ = ws.send(Message::Frame(Frame::message(
                    "two",
                    OpCode::Data(Data::Continue),
                    true,
                )));
            }
            "fragmentoversize" => {
                let _ = ws.send(Message::Frame(Frame::message(
                    vec![b'x'; 700],
                    OpCode::Data(Data::Text),
                    false,
                )));
                let _ = ws.send(Message::Frame(Frame::message(
                    vec![b'x'; 700],
                    OpCode::Data(Data::Continue),
                    true,
                )));
            }
            "oversize" => {
                let _ = ws.send(Message::Text("x".repeat(2048).into()));
            }
            "invalidutf8" => {
                let _ = ws.send(Message::Frame(Frame::message(
                    vec![255],
                    OpCode::Data(Data::Text),
                    true,
                )));
            }
            "slowread" => {
                let _ = ws.send(Message::Frame(Frame::message(
                    "partial",
                    OpCode::Data(Data::Text),
                    false,
                )));
                std::thread::sleep(Duration::from_secs(2));
            }
            "badclose" => {
                let _ = ws.get_mut().tcp.write_all(&[0x88, 0x01, 0]);
            }
            "controlflood" => {
                for _ in 0..100000 {
                    if ws.send(Message::Ping(Vec::new().into())).is_err() {
                        break;
                    }
                }
            }
            "fragmentflood" => {
                let _ = ws.send(Message::Frame(Frame::message(
                    Vec::new(),
                    OpCode::Data(Data::Text),
                    false,
                )));
                for _ in 0..100000 {
                    if ws
                        .send(Message::Frame(Frame::message(
                            Vec::new(),
                            OpCode::Data(Data::Continue),
                            false,
                        )))
                        .is_err()
                    {
                        break;
                    }
                }
            }
            _ => {}
        }
        loop {
            match ws.read() {
                Ok(Message::Close(_)) => {
                    if mode == "closehold" {
                        std::thread::sleep(Duration::from_secs(2));
                    } else {
                        let _ = ws.flush();
                    }
                    break;
                }
                Ok(Message::Text(text)) => {
                    if ws.send(Message::Text(text)).is_err() {
                        break;
                    }
                }
                Ok(Message::Binary(data)) => {
                    if ws.send(Message::Binary(data)).is_err() {
                        break;
                    }
                }
                Ok(_) => {
                    let _ = ws.flush();
                }
                Err(_) => break,
            }
        }
    }
}
