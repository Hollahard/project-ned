#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod policy;

use policy::HostError;
use serde_json::Value;
#[cfg(feature = "binding-fixture")]
use tauri::Manager;
use tauri::{WebviewUrl, WebviewWindow, WebviewWindowBuilder};

fn trusted(window: &WebviewWindow) -> Result<(), HostError> {
    if window.label() != "main" || !window.url().is_ok_and(|url| policy::local_origin(&url)) {
        return Err(HostError {
            code: "HERMES_HOST_FORBIDDEN",
            capability: "renderer-origin".into(),
        });
    }
    Ok(())
}

#[tauri::command]
fn hermes_host_request(
    window: WebviewWindow,
    method: String,
    args: Vec<Value>,
) -> Result<Value, HostError> {
    trusted(&window)?;
    policy::request(&method, &args)
}

#[cfg(feature = "binding-fixture")]
#[tauri::command]
fn hermes_binding_fixture(
    window: WebviewWindow,
    phase: String,
    checks: Option<Vec<String>>,
) -> Result<(), HostError> {
    use std::io::Write;
    use tauri::Emitter;
    trusted(&window)?;
    match phase.as_str() {
        "event" => window
            .emit(
                "hermes:host:event",
                serde_json::json!({"name":"boot-progress", "payload":{"stage":"binding-fixture"}}),
            )
            .map_err(|_| HostError {
                code: "HERMES_FIXTURE_EVENT_FAILED",
                capability: "fixture".into(),
            }),
        "finish" => {
            let checks = checks.unwrap_or_default();
            let result = serde_json::json!({"checks":checks, "mode":"native-tauri-fixture"});
            let output =
                std::env::var_os("HERMES_NATIVE_FIXTURE_RESULT").ok_or_else(|| HostError {
                    code: "HERMES_FIXTURE_NO_OUTPUT",
                    capability: "fixture".into(),
                })?;
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(output)
                .map_err(|_| HostError {
                    code: "HERMES_FIXTURE_OUTPUT_FAILED",
                    capability: "fixture".into(),
                })?;
            file.write_all(result.to_string().as_bytes())
                .map_err(|_| HostError {
                    code: "HERMES_FIXTURE_OUTPUT_FAILED",
                    capability: "fixture".into(),
                })?;
            println!("HERMES_BINDING_PROOF {}", result);
            window.app_handle().exit(0);
            Ok(())
        }
        _ => Err(HostError {
            code: "HERMES_FIXTURE_INVALID_PHASE",
            capability: "fixture".into(),
        }),
    }
}

fn main() {
    let builder = tauri::Builder::default();
    #[cfg(feature = "binding-fixture")]
    let builder = builder.invoke_handler(tauri::generate_handler![
        hermes_host_request,
        hermes_binding_fixture
    ]);
    #[cfg(not(feature = "binding-fixture"))]
    let builder = builder.invoke_handler(tauri::generate_handler![hermes_host_request]);
    builder
        .setup(|app| {
            #[cfg(feature = "binding-fixture")]
            app.add_capability(include_str!("../fixtures/fixture-capability.json"))?;
            let fixture = cfg!(feature = "binding-fixture");
            let retained_observation =
                fixture && std::env::var("HERMES_NATIVE_FIXTURE_MODE").as_deref() == Ok("retained");
            let page = if fixture && !retained_observation {
                "binding-proof.html"
            } else {
                "index.html"
            };
            // Unique profile isolation is required by the outer owned fixture runner.
            let profile = std::env::var_os("HERMES_NATIVE_WEBVIEW_PROFILE")
                .ok_or("Explicit disposable WebView profile required for this development shell")?;
            let profile = std::path::PathBuf::from(profile);
            if !profile.is_absolute() || !profile.is_dir() {
                return Err("Invalid WebView profile".into());
            }
            let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App(page.into()))
                .title("Hermes Native — incomplete binding proof")
                .visible(!fixture)
                .data_directory(profile)
                .initialization_script(include_str!("transport.js"))
                .on_navigation(|url| {
                    policy::local_origin(url)
                        && matches!(url.path(), "/" | "/index.html" | "/binding-proof.html")
                })
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny);
            if retained_observation {
                window = window.initialization_script(include_str!("retained-observer.js"));
            }
            window.build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Native binding shell failed");
}
