#[cfg(windows)]
mod windows_fixture;

fn main() {
    #[cfg(windows)]
    if let Err(error) = windows_fixture::run() {
        eprintln!("ERROR: {error}");
        std::process::exit(1);
    }
    #[cfg(not(windows))]
    {
        eprintln!("ERROR: this native fixture requires Windows and WebView2");
        std::process::exit(1);
    }
}
