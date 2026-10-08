#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod catalog;
mod control;
mod navigation;
mod policy;
mod preview;

use policy::HostError;
use serde_json::Value;
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
    preview: tauri::State<'_, preview::PreviewState>,
    method: String,
    args: Vec<Value>,
    document_id: Option<String>,
) -> Result<Value, HostError> {
    trusted(&window)?;
    policy::validate_request(&method, &args)?;
    if preview::supports(&method) {
        return preview
            .dispatch(&window, &method, &args, document_id.as_deref())
            .map_err(|error| HostError {
                code: error.code,
                capability: error.capability,
            });
    }
    policy::request(&method, &args)
}

#[tauri::command]
async fn hermes_model_inspect(
    window: WebviewWindow,
    state: tauri::State<'_, catalog::ShellCatalog>,
    model_path: String,
) -> Result<Value, hermes_catalog_host::CatalogError> {
    let permit = state.admit(&window, &model_path)?;
    match tauri::async_runtime::spawn_blocking(move || permit.inspect()).await {
        Ok(result) => result,
        Err(_) => {
            state.retire()?;
            Err(hermes_catalog_host::CatalogError {
                code: "CATALOG_FAILED",
                message: "The inspection task stopped unexpectedly.",
                retired: true,
            })
        }
    }
}

#[tauri::command]
async fn hermes_control_request(
    window: WebviewWindow,
    state: tauri::State<'_, control::ShellControl>,
    operation: String,
    payload: Value,
) -> Result<Value, hermes_control_host::ControlError> {
    trusted(&window).map_err(|_| hermes_control_host::ControlError::unavailable())?;
    let permit = state.admit(&window, &operation, &payload)?;
    tauri::async_runtime::spawn_blocking(move || permit.request(&operation, payload))
        .await
        .map_err(|_| hermes_control_host::ControlError::unavailable())?
}

#[cfg(feature = "binding-fixture")]
#[tauri::command]
async fn hermes_binding_fixture(
    window: WebviewWindow,
    phase: String,
    checks: Option<Vec<String>>,
) -> Result<Value, HostError> {
    use std::io::Write;
    use tauri::Emitter;
    trusted(&window)?;
    if phase.starts_with("catalog-") {
        return window
            .state::<catalog::ShellCatalog>()
            .fixture_phase(&window, &phase)
            .map_err(|error| HostError {
                code: error.code,
                capability: "catalog-fixture".into(),
            });
    }
    if phase.starts_with("preview-") {
        return window
            .state::<preview::PreviewState>()
            .fixture_phase(&window, &phase)
            .map_err(|error| HostError {
                code: error.code,
                capability: error.capability,
            });
    }
    match phase.as_str() {
        "event" => window
            .emit(
                "hermes:host:event",
                serde_json::json!({"name":"boot-progress", "payload":{"stage":"binding-fixture"}}),
            )
            .map(|_| Value::Null)
            .map_err(|_| HostError {
                code: "HERMES_FIXTURE_EVENT_FAILED",
                capability: "fixture".into(),
            }),
        "finish" => {
            let checks = checks.unwrap_or_default();
            let control = window.state::<control::ShellControl>();
            let cleanup = match control.retire() {
                Ok(report) => serde_json::json!({"verified":true,"report":report}),
                Err(error) => serde_json::json!({"verified":false,"error":error}),
            };
            let catalog_cleanup = match window.state::<catalog::ShellCatalog>().retire() {
                Ok(report) => serde_json::json!({"verified":true,"report":report}),
                Err(error) => serde_json::json!({"verified":false,"error":error}),
            };
            let result = serde_json::json!({"checks":checks, "mode":"native-tauri-fixture",
                "control_worker_started":control.started,"control_cleanup":cleanup,"catalog_cleanup":catalog_cleanup});
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
            Ok(Value::Null)
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
        hermes_model_inspect,
        hermes_control_request,
        hermes_binding_fixture
    ]);
    #[cfg(not(feature = "binding-fixture"))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        hermes_host_request,
        hermes_model_inspect,
        hermes_control_request
    ]);
    builder
        .setup(|app| {
            app.manage(control::ShellControl::new());
            app.manage(catalog::ShellCatalog::new());
            #[cfg(feature = "binding-fixture")]
            app.add_capability(include_str!("../fixtures/fixture-capability.json"))?;
            #[cfg(feature = "binding-fixture")]
            app.add_capability(include_str!("../fixtures/preview-observer-capability.json"))?;
            let fixture = cfg!(feature = "binding-fixture");
            let mode = std::env::var("HERMES_NATIVE_FIXTURE_MODE").unwrap_or_default();
            let retained_observation = fixture && mode == "retained";
            let profiles_observation = fixture && matches!(mode.as_str(), "profiles" | "catalog-profiles");
            let page = if fixture {
                match mode.as_str() {
                    "retained" | "profiles" | "catalog-profiles" => "index.html",
                    "preview" => "preview-proof.html",
                    "preview-reload" => "preview-reload-proof.html",
                    "catalog" => "catalog-proof.html",
                    "catalog-unavailable" => "catalog-unavailable-proof.html",
                    "control-create" => "control-create-proof.html",
                    "control-reopen" => "control-reopen-proof.html",
                    "control-unavailable" => "control-unavailable-proof.html",
                    _ => "binding-proof.html",
                }
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
            let navigation = std::sync::Arc::new(navigation::PreviewNavigationFence::default());
            let nav_fence = navigation.clone();
            let nav_app = app.handle().clone();
            let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App(page.into()))
                .title("Hermes Native — incomplete binding proof")
                .visible(!fixture)
                .data_directory(profile)
                .initialization_script(include_str!("transport.js"))
                .on_navigation(move |url| {
                    let allowed = policy::local_origin(url)
                        && matches!(
                            url.path(),
                            "/" | "/index.html"
                                | "/binding-proof.html"
                                | "/preview-proof.html"
                                | "/preview-reload-proof.html"
                                | "/catalog-proof.html"
                                | "/catalog-unavailable-proof.html"
                                | "/control-create-proof.html"
                                | "/control-reopen-proof.html"
                                | "/control-unavailable-proof.html"
                        );
                    if allowed && nav_fence.on_allowed_navigation() {
                        if let Some(preview) = nav_app.try_state::<preview::PreviewState>() {
                            preview.retire();
                        }
                        if let Some(catalog) = nav_app.try_state::<catalog::ShellCatalog>() {
                            if let Err(error) = catalog.retire() { eprintln!("{}", error.code); }
                        }
                    }
                    allowed
                })
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny);
            if retained_observation {
                window = window.initialization_script(include_str!("retained-observer.js"));
            }
            if profiles_observation {
                if mode == "catalog-profiles" {
                    window = window.initialization_script("Object.defineProperty(window, '__HERMES_CATALOG_FIXTURE__', {value:true,writable:false,configurable:false});");
                }
                window = window.initialization_script(include_str!("profiles-observer.js"));
            }
            let window = window.build()?;
            app.state::<control::ShellControl>().bind(&window)?;
            app.state::<catalog::ShellCatalog>().bind(&window)?;
            app.manage(preview::PreviewState::new(window)?);
            if navigation.retirement_requested() {
                app.state::<preview::PreviewState>().retire();
                if let Err(error) = app.state::<catalog::ShellCatalog>().retire() { eprintln!("{}", error.code); }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Native binding shell failed")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(catalog) = app.try_state::<catalog::ShellCatalog>() {
                    if let Err(error) = catalog.retire() { eprintln!("{}", error.code); }
                }
                if let Some(control) = app.try_state::<control::ShellControl>() {
                    if let Err(error) = control.retire() {
                        eprintln!("{}", error.code);
                    }
                }
            }
        });
}
