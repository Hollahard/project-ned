pub mod approvals;
pub mod commands;
pub mod first_launch;
pub mod processes;
pub mod proxy;
pub mod runtime;

use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::info;

use commands::AppState;
use runtime::{SupervisorConfig, SupervisorRuntime};

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter("info,project_friday=debug")
        .init();

    info!("Initializing Project Friday Tauri Desktop Supervisor...");

    let supervisor_config = SupervisorConfig::default();
    let runtime = Arc::new(RwLock::new(SupervisorRuntime::new(supervisor_config)));
    let runtime_clone = runtime.clone();

    tauri::Builder::default()
        .manage(runtime.clone() as AppState)
        .setup(move |_app| {
            let rt = runtime_clone.clone();
            tauri::async_runtime::spawn(async move {
                let mut guard = rt.write().await;
                if let Err(e) = guard.start().await {
                    tracing::error!("Failed to start supervisor runtime: {}", e);
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_runtime_status,
            commands::list_models,
            commands::load_model,
            commands::unload_model,
            commands::create_session,
            commands::list_sessions,
            commands::cancel_turn,
            commands::trigger_native_approval_test,
            commands::request_tool_approval,
            commands::get_gpu_telemetry,
            commands::check_vram_preflight,
            commands::activate_gaming_mode,
            commands::deactivate_gaming_mode,
            commands::get_gaming_mode_status,
            commands::check_first_launch,
            commands::run_first_launch_diagnostics,
            commands::complete_first_launch,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |app_handle, event| {
            match event {
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                    info!("Exit requested. Stopping supervisor and terminating child processes...");
                    let rt = runtime.clone();
                    tauri::async_runtime::block_on(async move {
                        let mut guard = rt.write().await;
                        guard.stop().await;
                    });
                }
                tauri::RunEvent::WindowEvent {
                    event: tauri::WindowEvent::CloseRequested { .. },
                    ..
                } => {
                    info!("Window close requested. Exiting application and stopping supervisor...");
                    app_handle.exit(0);
                }
                _ => {}
            }
        });
}
