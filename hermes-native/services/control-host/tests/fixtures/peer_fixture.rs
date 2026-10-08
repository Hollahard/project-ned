//! Harmless protocol peer selected explicitly by a test-only pinned manifest.
use std::io::{BufRead, Write};
fn main() {
    let mode = std::env::current_dir()
        .unwrap()
        .file_name()
        .unwrap()
        .to_string_lossy()
        .into_owned();
    if mode.starts_with("unrelated") {
        loop {
            std::thread::sleep(std::time::Duration::from_secs(30));
        }
    }
    if mode.starts_with("bad-hello") {
        println!("{{\"type\":\"ready\",\"protocol\":\"wrong\"}}");
        std::io::stdout().flush().unwrap();
        std::thread::sleep(std::time::Duration::from_secs(30));
        return;
    }
    println!("{{\"type\":\"ready\",\"protocol\":\"hermes-control-v1\",\"service\":\"hermes-control-worker\",\"runtime_attached\":false}}");
    std::io::stdout().flush().unwrap();
    for line in std::io::stdin().lock().lines() {
        let value: serde_json::Value = serde_json::from_str(&line.unwrap()).unwrap();
        let method = value["method"].as_str().unwrap();
        let id = value["id"].as_str().unwrap();
        if method == "service.describe" {
            let mut methods = hermes_control_host::OPERATIONS.to_vec();
            methods.extend(["service.describe", "service.shutdown"]);
            println!(
                "{}",
                serde_json::json!({"id":id,"result":{"protocol":"hermes-control-v1","service":"hermes-control-worker","methods":methods,"max_frame_bytes":65536,"max_requests":4096,"runtime_attached":false,"admission_allowed":false}})
            );
        } else if method == "service.shutdown" {
            println!(
                "{}",
                serde_json::json!({"id":id,"result":{"stopping":true}})
            );
            std::io::stdout().flush().unwrap();
            if mode.starts_with("tail-complete") {
                std::thread::sleep(std::time::Duration::from_millis(40));
                println!(
                    "{}",
                    serde_json::json!({"id":id,"result":{"stopping":true}})
                );
                std::io::stdout().flush().unwrap();
            } else if mode.starts_with("tail-partial") {
                std::thread::sleep(std::time::Duration::from_millis(40));
                print!("{{\"trailing\":");
                std::io::stdout().flush().unwrap();
            }
            break;
        } else if mode.starts_with("timeout") {
            std::thread::sleep(std::time::Duration::from_secs(30));
        } else if mode.starts_with("crash") {
            std::process::exit(7);
        } else if mode.starts_with("truncated") {
            print!("{{\"id\":\"{id}\",\"result\":");
            std::io::stdout().flush().unwrap();
            return;
        } else if mode.starts_with("duplicate") {
            println!("{{\"id\":\"{id}\",\"id\":\"{id}\",\"result\":{{}}}}");
        } else if mode.starts_with("unknown") {
            println!(
                "{}",
                serde_json::json!({"id":id,"result":{},"api_key":"must-not-escape"})
            );
        } else {
            println!("{}", serde_json::json!({"id":"wrong","result":{}}));
        }
        std::io::stdout().flush().unwrap();
    }
}
