//! Harmless test child. Not built unless the test-fixture feature is enabled.
use std::path::PathBuf;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args().skip(1);
    match arguments.next().as_deref() {
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
