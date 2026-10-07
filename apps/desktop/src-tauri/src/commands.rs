//! Tauri IPC command handlers for Project Friday desktop.
//!
//! Invariants:
//! 1. All commands interact exclusively with the in-memory Supervisor runtime.
//! 2. Bearer tokens and admin keys are never exposed in command responses.
//! 3. High-risk executions gate on native approvals and one-shot tokens.

use std::sync::Arc;
use tauri::State;
use tokio::sync::RwLock;

use crate::first_launch::{
    check_first_launch_status, execute_first_launch_setup, run_preflight_diagnostics,
    FirstLaunchDiagnostics, FirstLaunchSetupRequest, FirstLaunchSetupResponse, FirstLaunchStatus,
};
use crate::proxy::{
    GamingModeStatus, GpuTelemetry, ModelProfile, PreflightRequest, PreflightResult, RuntimeStatus,
    SessionSummary,
};
use crate::runtime::SupervisorRuntime;

pub type AppState = Arc<RwLock<SupervisorRuntime>>;

#[tauri::command]
pub async fn get_runtime_status(state: State<'_, AppState>) -> Result<RuntimeStatus, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy
        .get_runtime_status()
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn list_models(state: State<'_, AppState>) -> Result<Vec<ModelProfile>, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.list_models().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn load_model(
    state: State<'_, AppState>,
    model_id: String,
) -> Result<serde_json::Value, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.load_model(&model_id).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn unload_model(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.unload_model().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn create_session(
    state: State<'_, AppState>,
    title: Option<String>,
) -> Result<SessionSummary, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy
        .create_session(title.as_deref(), None)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn list_sessions(state: State<'_, AppState>) -> Result<Vec<SessionSummary>, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.list_sessions().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn cancel_turn(state: State<'_, AppState>, session_id: String) -> Result<(), String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.cancel_turn(&session_id).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn trigger_native_approval_test(
    state: State<'_, AppState>,
    tool_name: String,
    arguments: serde_json::Value,
    risk_reason: String,
    turn_id: String,
) -> Result<String, String> {
    let runtime = state.read().await;
    let approvals = runtime.approvals().ok_or("Approval manager not initialized")?;
    approvals
        .request_approval_and_mint(&tool_name, &arguments, &risk_reason, &turn_id)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn request_tool_approval(
    state: State<'_, AppState>,
    tool_name: String,
    arguments: serde_json::Value,
    risk_reason: String,
    turn_id: String,
) -> Result<String, String> {
    let runtime = state.read().await;
    let approvals = runtime.approvals().ok_or("Approval manager not initialized")?;
    approvals
        .request_approval_and_mint(&tool_name, &arguments, &risk_reason, &turn_id)
        .map_err(|e| e.to_string())
}


#[tauri::command]
pub async fn get_gpu_telemetry(state: State<'_, AppState>) -> Result<GpuTelemetry, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.get_gpu_telemetry().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn check_vram_preflight(
    state: State<'_, AppState>,
    request: PreflightRequest,
) -> Result<PreflightResult, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy
        .check_vram_preflight(&request)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn activate_gaming_mode(state: State<'_, AppState>) -> Result<GamingModeStatus, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.activate_gaming_mode().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn deactivate_gaming_mode(state: State<'_, AppState>) -> Result<GamingModeStatus, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.deactivate_gaming_mode().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_gaming_mode_status(state: State<'_, AppState>) -> Result<GamingModeStatus, String> {
    let runtime = state.read().await;
    let proxy = runtime.proxy().ok_or("Supervisor proxy not initialized")?;
    proxy.get_gaming_mode_status().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn check_first_launch() -> Result<FirstLaunchStatus, String> {
    Ok(check_first_launch_status(None))
}

#[tauri::command]
pub async fn run_first_launch_diagnostics() -> Result<FirstLaunchDiagnostics, String> {
    Ok(run_preflight_diagnostics())
}

#[tauri::command]
pub async fn complete_first_launch(
    request: FirstLaunchSetupRequest,
) -> Result<FirstLaunchSetupResponse, String> {
    execute_first_launch_setup(&request)
}

