#![cfg(windows)]
use hermes_terminal_host::{Terminal, TerminalSpec};
use std::collections::BTreeMap;
use std::io;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

const DEADLINE: Duration = Duration::from_secs(8);

fn spec(capacity: usize) -> TerminalSpec {
    TerminalSpec {
        executable: PathBuf::from(env!("CARGO_BIN_EXE_terminal-fixture")),
        arguments: Vec::new(),
        working_directory: PathBuf::from(env!("CARGO_MANIFEST_DIR")),
        environment: BTreeMap::from([(
            "SystemRoot".into(),
            std::env::var("SystemRoot").expect("Windows SystemRoot"),
        )]),
        columns: 120,
        rows: 30,
        output_capacity: capacity,
    }
}

fn until(terminal: &Terminal, marker: &str) -> Vec<u8> {
    let deadline = Instant::now() + DEADLINE;
    let mut output = Vec::new();
    while !output
        .windows(marker.len())
        .any(|part| part == marker.as_bytes())
    {
        assert!(
            output.len() < 65_536,
            "fixture output exceeded expected bound"
        );
        let chunk = terminal
            .read(4096, deadline.saturating_duration_since(Instant::now()))
            .unwrap_or_else(|error| {
                panic!(
                    "waiting for {marker:?}: {error}; received {:?}",
                    String::from_utf8_lossy(&output)
                )
            });
        assert!(!chunk.overflowed, "unexpected fixture output loss");
        assert!(
            !chunk.eof || !chunk.bytes.is_empty(),
            "fixture exited before marker; got {}",
            String::from_utf8_lossy(&output)
        );
        output.extend(chunk.bytes);
    }
    output
}

#[test]
fn unicode_input_output_resize_and_natural_exit() {
    let mut terminal = Terminal::spawn(spec(65_536)).expect("create native ConPTY");
    until(&terminal, "READY:héllo漢字🙂");
    terminal.write("ECHO naïve世界🙂\r".as_bytes()).unwrap();
    until(&terminal, "ECHOED:naïve世界🙂");
    terminal.resize(93, 27).unwrap();
    terminal.write(b"SIZE\r").unwrap();
    until(&terminal, "SIZE:93x27");
    terminal.write(b"QUIT\r").unwrap();
    until(&terminal, "BYE");
    assert_eq!(terminal.wait(DEADLINE).unwrap(), Some(7));
    terminal.close().unwrap();
    assert_eq!(terminal.active_processes().unwrap(), 0);
    assert_eq!(
        terminal.write(b"after-close").unwrap_err().kind(),
        io::ErrorKind::BrokenPipe
    );
}

struct OwnedFixture(Child);
impl Drop for OwnedFixture {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn cancellation_reaps_owned_descendant_and_leaves_unrelated_fixture_running() {
    let mut unrelated = OwnedFixture(
        Command::new(env!("CARGO_BIN_EXE_terminal-fixture"))
            .arg("--idle")
            .env_clear()
            .env("SystemRoot", std::env::var("SystemRoot").unwrap())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .unwrap(),
    );
    let mut terminal = Terminal::spawn(spec(65_536)).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    terminal.write(b"SPAWN\r").unwrap();
    until(&terminal, "CHILD:");
    assert!(
        terminal.active_processes().unwrap() >= 2,
        "fixture child should inherit terminal job"
    );
    terminal.close().unwrap();
    assert!(terminal.wait(DEADLINE).unwrap().is_some());
    let deadline = Instant::now() + DEADLINE;
    while terminal.active_processes().unwrap() != 0 {
        assert!(Instant::now() < deadline, "owned descendants did not exit");
        std::thread::yield_now();
    }
    assert!(
        unrelated.0.try_wait().unwrap().is_none(),
        "unrelated fixture was terminated"
    );
    // Only our explicit unrelated fixture guard reaps this separate control process.
}

#[test]
fn output_is_bounded_and_overflow_is_visible_without_blocking_cleanup() {
    let mut terminal = Terminal::spawn(spec(1024)).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    terminal.write(b"FLOOD_EXIT\r").unwrap();
    // Exit follows the complete write workload, so this does not depend on a sleep.
    assert_eq!(terminal.wait(DEADLINE).unwrap(), Some(9));
    let chunk = terminal.read(1_048_576, DEADLINE).unwrap();
    assert!(chunk.bytes.len() <= 1024);
    assert!(
        chunk.overflowed,
        "fixture must exceed the bounded output capacity"
    );
    terminal.close().unwrap();
    assert_eq!(terminal.active_processes().unwrap(), 0);
}

#[test]
fn reads_have_deadlines_and_invalid_input_is_rejected() {
    let mut terminal = Terminal::spawn(spec(65_536)).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    // Drain any trailing VT cursor bytes; eventually an idle fixture reaches the deadline.
    let deadline = Instant::now() + DEADLINE;
    loop {
        assert!(
            Instant::now() < deadline,
            "idle fixture kept producing output"
        );
        match terminal.read(4096, Duration::from_millis(50)) {
            Err(error) => {
                assert_eq!(error.kind(), io::ErrorKind::TimedOut);
                break;
            }
            Ok(chunk) => {
                assert!(!chunk.eof);
            }
        }
    }
    assert_eq!(
        terminal.read(0, DEADLINE).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    assert_eq!(
        terminal.write(&vec![0; 4097]).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    assert_eq!(
        terminal.resize(0, 12).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    terminal.close().unwrap();
}

#[test]
fn failed_creation_cleans_up_pty_and_io_threads() {
    let mut invalid = spec(4096);
    invalid
        .environment
        .insert("bad=name".into(), "fixture".into());
    let start = Instant::now();
    assert!(Terminal::spawn(invalid).is_err());
    let mut not_an_executable = spec(4096);
    not_an_executable.executable = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
    assert!(Terminal::spawn(not_an_executable).is_err());
    assert!(start.elapsed() < DEADLINE);
    // A fresh session after failure exercises the same native allocation/cleanup path.
    let mut terminal = Terminal::spawn(spec(4096)).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    terminal.close().unwrap();
}

#[test]
fn argument_quoting_and_explicit_environment_survive_native_process_creation() {
    let mut config = spec(65_536);
    let argument = "space 漢字 \\\"quoted\\\" trailing\\";
    config.arguments.push(argument.into());
    config
        .environment
        .insert("HERMES_FIXTURE_VALUE".into(), "fixture-only".into());
    let mut terminal = Terminal::spawn(config).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    terminal.write(b"PROBE\r").unwrap();
    let output = until(&terminal, "ENV_FIXTURE:fixture-only");
    let text = String::from_utf8_lossy(&output);
    assert!(text.contains(&format!("ARGV:{argument}")));
    assert!(
        text.contains("ENV_COUNT:2"),
        "parent environment must not be inherited"
    );
    terminal.close().unwrap();
}

#[test]
fn eof_is_reported_only_after_all_retained_output_is_drained() {
    let mut terminal = Terminal::spawn(spec(65_536)).unwrap();
    until(&terminal, "READY:héllo漢字🙂");
    terminal.write(b"TAIL_EXIT\r").unwrap();
    assert_eq!(terminal.wait(DEADLINE).unwrap(), Some(11));
    // Closing ConPTY joins the output reader and preserves its buffered bytes.
    terminal.close().unwrap();
    let mut complete = Vec::new();
    let mut chunks = 0;
    loop {
        let chunk = terminal.read(7, DEADLINE).unwrap();
        assert!(!chunk.overflowed);
        assert!(chunk.bytes.len() <= 7);
        complete.extend(chunk.bytes);
        chunks += 1;
        if chunk.eof {
            break;
        }
        assert!(
            chunks < 10_000,
            "EOF did not arrive within the retained buffer bound"
        );
    }
    assert!(chunks > 1);
    assert!(String::from_utf8_lossy(&complete).contains(
        "FINAL-OUTPUT:0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-END"
    ));
    let finished = terminal.read(7, DEADLINE).unwrap();
    assert!(finished.eof && finished.bytes.is_empty());
}
