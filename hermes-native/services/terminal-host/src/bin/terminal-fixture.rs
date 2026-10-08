use std::io::{self, BufRead, Write};
use std::process::Command;
use std::time::Duration;
#[cfg(windows)]
use windows_sys::Win32::System::Console::*;

fn main() -> io::Result<()> {
    if std::env::args().any(|arg| arg == "--idle") {
        std::thread::sleep(Duration::from_secs(60));
        return Ok(());
    }
    #[cfg(windows)]
    unsafe {
        SetConsoleCP(65001);
        SetConsoleOutputCP(65001);
        SetConsoleMode(
            GetStdHandle(STD_INPUT_HANDLE),
            ENABLE_LINE_INPUT | ENABLE_PROCESSED_INPUT,
        );
    }
    println!("READY:héllo漢字🙂");
    io::stdout().flush()?;
    for line in io::stdin().lock().lines() {
        let line = line?;
        if let Some(text) = line.strip_prefix("ECHO ") {
            println!("ECHOED:{text}");
        } else if line == "PROBE" {
            println!("ARGV:{}", std::env::args().nth(1).unwrap_or_default());
            println!("ENV_COUNT:{}", std::env::vars_os().count());
            println!(
                "ENV_FIXTURE:{}",
                std::env::var("HERMES_FIXTURE_VALUE").unwrap_or_default()
            );
        } else if line == "SIZE" {
            #[cfg(windows)]
            unsafe {
                let mut info: CONSOLE_SCREEN_BUFFER_INFO = std::mem::zeroed();
                if GetConsoleScreenBufferInfo(GetStdHandle(STD_OUTPUT_HANDLE), &mut info) == 0 {
                    return Err(io::Error::last_os_error());
                }
                println!(
                    "SIZE:{}x{}",
                    info.srWindow.Right - info.srWindow.Left + 1,
                    info.srWindow.Bottom - info.srWindow.Top + 1
                );
            }
        } else if line == "SPAWN" {
            let child = Command::new(std::env::current_exe()?)
                .arg("--idle")
                .spawn()?;
            println!("CHILD:{}", child.id());
            // Deliberately retained by the terminal Job, not reaped individually by the fixture.
            drop(child);
        } else if line == "FLOOD_EXIT" {
            for _ in 0..4096 {
                println!("bounded-output-fixture-abcdefghijklmnopqrstuvwxyz0123456789");
            }
            println!("FLOOD-DONE");
            io::stdout().flush()?;
            std::process::exit(9);
        } else if line == "TAIL_EXIT" {
            println!(
                "FINAL-OUTPUT:0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-END"
            );
            io::stdout().flush()?;
            std::process::exit(11);
        } else if line == "QUIT" {
            println!("BYE");
            io::stdout().flush()?;
            std::process::exit(7);
        }
        io::stdout().flush()?;
    }
    Ok(())
}
