//! Explicit diagnostic CLI: no implicit grants, config discovery or model load.
#[cfg(windows)]
fn main() {
    use hermes_catalog_host::CatalogState;
    use std::io::Write;
    use std::path::Path;
    use std::time::Duration;
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 4 || args[0] != "--config" || args[2] != "--model" {
        eprintln!("Usage: inspect --config <absolute receipt> --model <absolute model folder>");
        std::process::exit(2);
    }
    let Some(model) = args[3].to_str() else {
        eprintln!("Invalid model path encoding.");
        std::process::exit(2);
    };
    let state = match CatalogState::from_config(Path::new(&args[1])) {
        Ok(state) => state,
        Err(error) => {
            println!(
                "{}",
                serde_json::json!({"result":null,"error":error,"cleanup":null})
            );
            std::process::exit(2);
        }
    };
    let result = state.try_admit(model).and_then(|permit| permit.inspect());
    let retirement = state.retire(Duration::from_secs(5));
    let success = result.is_ok()
        && retirement
            .as_ref()
            .is_ok_and(|report| report.as_ref().is_some_and(|proof| proof.verified));
    let output = match retirement {
        Ok(cleanup) => match result {
            Ok(result) => serde_json::json!({"result":result,"error":null,"cleanup":cleanup}),
            Err(error) => serde_json::json!({"result":null,"error":error,"cleanup":cleanup}),
        },
        Err(error) => serde_json::json!({"result":null,"error":error,"cleanup":null}),
    };
    let mut bytes = serde_json::to_vec(&output).expect("finite JSON output");
    bytes.push(b'\n');
    if bytes.len() > 67_584 || std::io::stdout().lock().write_all(&bytes).is_err() {
        eprintln!("Inspection result output failed.");
        std::process::exit(2);
    }
    std::process::exit(if success { 0 } else { 2 });
}
#[cfg(not(windows))]
fn main() {
    eprintln!("This diagnostic requires Windows.");
    std::process::exit(2);
}
