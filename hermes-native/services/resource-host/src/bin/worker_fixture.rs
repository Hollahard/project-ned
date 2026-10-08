//! Harmless test child. Not built unless the test-fixture feature is enabled.
use std::path::PathBuf;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::{Read, Write};
    let mut arguments = std::env::args().skip(1);
    match arguments.next().as_deref() {
        Some("framed-echo") => {
            use std::io::BufRead;
            std::io::stdout().write_all(b"{\"type\":\"ready\"}\n")?;
            std::io::stdout().flush()?;
            let mut reader = std::io::stdin().lock();
            let mut frame = Vec::new();
            while reader.read_until(b'\n', &mut frame)? != 0 {
                if frame == b"shutdown\n" {
                    std::io::stdout().write_all(b"{\"stopped\":true}\n")?;
                    std::io::stdout().flush()?;
                    break;
                }
                std::io::stdout().write_all(&frame)?;
                std::io::stdout().flush()?;
                frame.clear();
            }
        }
        Some("framed-no-read") => {
            std::io::stdout().write_all(b"{\"type\":\"ready\"}\n")?;
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("framed-overflow") => {
            std::io::stdout().write_all(b"{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n")?;
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("framed-long") => {
            std::io::stdout().write_all(&[b'x'; 65_536])?;
        }
        Some("framed-invalid") => {
            std::io::stdout().write_all(b"\xff\n")?;
        }
        Some("framed-partial") => {
            std::io::stdout().write_all(b"{\"partial\":")?;
        }
        Some("ready") => {
            assert_eq!(std::io::stdin().read(&mut [0u8; 1])?, 0);
            println!("HERMES_BACKEND_READY port=31415");
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        #[cfg(windows)]
        Some("inheritance") => {
            use windows_sys::Win32::System::Threading::SetEvent;
            let handle: usize = arguments.next().ok_or("missing probe handle")?.parse()?;
            let inherited = unsafe { SetEvent(handle as *mut std::ffi::c_void) } != 0;
            println!("inherited={inherited}");
            println!("HERMES_BACKEND_READY port=31415");
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("stderr-flood") => {
            let bytes = [b'x'; 65_536];
            for _ in 0..64 {
                std::io::stderr().write_all(&bytes)?;
            }
            println!("HERMES_BACKEND_READY port=31415");
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("malformed") => {
            println!("HERMES_BACKEND_READY port=31415 EXTRA");
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("conflict") => {
            std::io::stdout()
                .write_all(b"HERMES_BACKEND_READY port=31415\nHERMES_BACKEND_READY port=31416\n")?;
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("long-line") => {
            std::io::stdout().write_all(&[b'x'; 65_536])?;
            std::io::stdout().flush()?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("early-exit") => {
            print!("HERMES_BACKEND_READY port=31415");
        }
        Some("descendant-output") => {
            let destination = PathBuf::from(arguments.next().ok_or("missing output")?);
            let mut command = std::process::Command::new(std::env::current_exe()?);
            command.arg("sleep");
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let child = command.spawn()?;
            std::fs::write(destination, child.id().to_string())?;
            println!("HERMES_BACKEND_READY port=31415");
        }
        Some("dump") => {
            let destination = PathBuf::from(arguments.next().ok_or("missing output")?);
            let payload = serde_json::json!({
                "arguments": arguments.collect::<Vec<_>>(),
                "directory": std::env::current_dir()?.to_string_lossy(),
                "environment_keys": std::env::vars_os().map(|(key, _)| key.to_string_lossy().into_owned()).collect::<Vec<_>>(),
                "allowed_value": std::env::var("HERMES_TEST_VALUE").ok(),
            });
            std::fs::write(destination, serde_json::to_vec(&payload)?)?;
        }
        Some("sleep") => loop {
            std::thread::sleep(Duration::from_secs(1));
        },
        #[cfg(windows)]
        Some("own") => {
            use hermes_resource_host::{WorkerGroup, WorkerSpec};
            let destination = PathBuf::from(arguments.next().ok_or("missing output")?);
            let group = WorkerGroup::new()?;
            let worker = group.spawn(&WorkerSpec {
                executable: std::env::current_exe()?,
                arguments: vec!["sleep".into()],
                working_directory: std::env::current_dir()?,
                environment: Default::default(),
            })?;
            std::fs::write(destination, worker.id().to_string())?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        Some("descendant") => {
            let destination = PathBuf::from(arguments.next().ok_or("missing output")?);
            let mut command = std::process::Command::new(std::env::current_exe()?);
            command.arg("sleep");
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000); // CREATE_NO_WINDOW
            }
            let child = command.spawn()?;
            std::fs::write(destination, child.id().to_string())?;
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        _ => return Err("unknown fixture mode".into()),
    }
    Ok(())
}
