use std::io::{Read, Write};
use std::net::TcpListener;
use std::time::Duration;

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let mode = args.get(1).map(String::as_str).unwrap_or("good");
    if mode == "descendant" {
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["good", &args[2]])
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
    for stream in listener.incoming() {
        let mut stream = stream.unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut request = Vec::new();
        let mut byte = [0u8; 1];
        loop {
            match stream.read(&mut byte) {
                Ok(0) | Err(_) => break,
                Ok(_) => request.push(byte[0]),
            }
            if let Some(end) = request.windows(4).position(|b| b == b"\r\n\r\n") {
                let body = if request.starts_with(b"POST ") { 2 } else { 0 };
                if request.len() >= end + 4 + body {
                    break;
                }
            }
            if request.len() > 4096 {
                break;
            }
        }
        // Only the byte count is recorded, never application bytes or tokens.
        std::fs::write(&args[2], request.len().to_string()).unwrap();
        if request.is_empty() {
            continue;
        }
        let response: &[u8] = match mode {
            "good" => b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n{\"ok\":true}",
            "chunked" => b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n6\r\n{\"ok\":\r\n5\r\ntrue}\r\n0\r\n\r\n",
            "close" => b"HTTP/1.0 200 OK\r\n\r\n{\"ok\":true}",
            "malformed" => b"HTTP/1.1 200 OK\nContent-Length: 0\r\n\r\n",
            "oversize" => b"HTTP/1.1 200 OK\r\nContent-Length: 1048577\r\n\r\n",
            "dupe" => b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n",
            "redirect" => b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:9/\r\nContent-Length: 0\r\n\r\n",
            "truncated" => b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{",
            "trailing" => b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\nextra",
            "tecl" => b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
            "trailer" => b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX: a\r\n\r\n",
            "holdclose" => {
                let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n");
                std::thread::sleep(Duration::from_secs(2));
                continue;
            }
            "slow" => {
                for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n" {
                    if stream.write_all(&[*byte]).is_err() {break;}
                    std::thread::sleep(Duration::from_millis(30));
                }
                continue;
            }
            "hugeheaders" => {
                let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nX: ");
                let _ = stream.write_all(&vec![b'a'; 65536]);
                continue;
            }
            "chunkoversize" => b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n100001\r\n",
            "closeoversize" => {
                let _ = stream.write_all(b"HTTP/1.1 200 OK\r\n\r\n");
                let _ = stream.write_all(&vec![b'x'; 1024 * 1024 + 1]);
                continue;
            }
            _ => panic!("unknown fixture mode"),
        };
        let _ = stream.write_all(response);
    }
}
