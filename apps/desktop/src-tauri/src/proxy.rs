//! Rust reverse proxy client for Core FastAPI and TabbyAPI.
//!
//! Invariants:
//! 1. Bearer tokens and Tabby admin keys reside strictly in Rust supervisor memory.
//! 2. The React/WebView frontend NEVER touches or observes these keys.
//! 3. All outgoing requests to Core and Tabby are loopback-only and signed with the active token.

use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, thiserror::Error)]
pub enum ProxyError {
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),
    #[error("Core API returned error status {status}: {body}")]
    CoreError { status: StatusCode, body: String },
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("Inference server offline or unreachable: {0}")]
    InferenceUnreachable(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    pub status: String,
    pub version: String,
    pub uptime_seconds: f64,
    pub inference_backend: Option<String>,
    pub gpu_available: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelProfile {
    pub id: String,
    pub name: String,
    pub parameters_b: Option<f64>,
    pub resident: bool,
    pub loaded: bool,
    pub vram_estimate_mb: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuTelemetry {
    #[serde(default)]
    pub available: bool,
    #[serde(default)]
    pub device_name: String,
    #[serde(default)]
    pub driver_version: String,
    #[serde(default)]
    pub nvml_version: String,
    #[serde(default)]
    pub vram_total_mb: f64,
    #[serde(default)]
    pub vram_used_mb: f64,
    #[serde(default)]
    pub vram_free_mb: f64,
    #[serde(default)]
    pub vram_usage_percent: f64,
    #[serde(default)]
    pub temperature_c: i64,
    #[serde(default)]
    pub power_watts: f64,
    #[serde(default)]
    pub power_limit_watts: f64,
    #[serde(default)]
    pub utilization_gpu_percent: i64,
    #[serde(default)]
    pub utilization_mem_percent: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreflightRequest {
    pub model_name: String,
    #[serde(default = "default_context_length")]
    pub context_length: u32,
    #[serde(default = "default_kv_cache")]
    pub kv_cache_dtype: String,
    pub available_vram_mb: Option<f64>,
    pub bpw: Option<f64>,
}

fn default_context_length() -> u32 {
    32768
}

fn default_kv_cache() -> String {
    "q6".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreflightResult {
    pub fits: bool,
    pub model_name: String,
    pub context_length: u32,
    pub kv_cache_dtype: String,
    pub estimated_weights_mb: f64,
    pub estimated_kv_cache_mb: f64,
    pub estimated_total_mb: f64,
    pub available_vram_mb: f64,
    pub headroom_mb: f64,
    pub recommended_context: Option<u32>,
    pub recommended_kv_cache: Option<String>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GamingModeStatus {
    pub active: bool,
    pub activated_at: Option<f64>,
    pub elapsed_seconds: f64,
    pub vram_freed_mb: f64,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeStatus {
    pub core_status: String,
    pub inference_status: String,
    pub active_model: Option<String>,
    pub vram_allocated_mb: Option<f64>,
    pub vram_total_mb: Option<f64>,
    pub gpu_telemetry: Option<GpuTelemetry>,
    pub gaming_mode: Option<GamingModeStatus>,
}

fn deserialize_flexible_string<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    struct StringVisitor;

    impl<'de> serde::de::Visitor<'de> for StringVisitor {
        type Value = String;

        fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
            formatter.write_str("string or number")
        }

        fn visit_str<E>(self, value: &str) -> Result<String, E>
        where
            E: serde::de::Error,
        {
            Ok(value.to_string())
        }

        fn visit_string<E>(self, value: String) -> Result<String, E>
        where
            E: serde::de::Error,
        {
            Ok(value)
        }

        fn visit_f64<E>(self, value: f64) -> Result<String, E>
        where
            E: serde::de::Error,
        {
            Ok(value.to_string())
        }

        fn visit_u64<E>(self, value: u64) -> Result<String, E>
        where
            E: serde::de::Error,
        {
            Ok(value.to_string())
        }

        fn visit_i64<E>(self, value: i64) -> Result<String, E>
        where
            E: serde::de::Error,
        {
            Ok(value.to_string())
        }
    }

    deserializer.deserialize_any(StringVisitor)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionSummary {
    pub id: String,
    pub title: String,
    #[serde(default, deserialize_with = "deserialize_flexible_string")]
    pub created_at: String,
    #[serde(default, deserialize_with = "deserialize_flexible_string")]
    pub updated_at: String,
    #[serde(default)]
    pub message_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnRequest {
    pub prompt: String,
    pub attachments: Option<Vec<String>>,
    pub cloud_fallback: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageRecord {
    pub id: String,
    pub session_id: String,
    pub role: String,
    pub content: String,
    pub created_at: String,
}

/// Secure reverse proxy client holding credentials in memory.
pub struct CoreProxy {
    client: Client,
    core_base_url: String,
    core_bearer_token: Arc<String>,
    tabby_base_url: String,
    tabby_admin_key: Arc<String>,
}

impl CoreProxy {
    pub fn new(
        core_port: u16,
        core_bearer_token: String,
        tabby_port: u16,
        tabby_admin_key: String,
    ) -> Self {
        Self {
            client: Client::builder().no_proxy().build().unwrap(),
            core_base_url: format!("http://127.0.0.1:{}", core_port),
            core_bearer_token: Arc::new(core_bearer_token),
            tabby_base_url: format!("http://127.0.0.1:{}", tabby_port),
            tabby_admin_key: Arc::new(tabby_admin_key),
        }
    }

    /// Check Core health endpoint.
    pub async fn check_health(&self) -> Result<HealthStatus, ProxyError> {
        let url = format!("{}/health", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<HealthStatus>().await?;
        Ok(data)
    }

    /// Query unified runtime status (Core + Tabby + GPU).
    pub async fn get_runtime_status(&self) -> Result<RuntimeStatus, ProxyError> {
        let url = format!("{}/api/v1/runtime/status", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let raw: serde_json::Value = res.json().await?;
        let core_status = raw["status"].as_str().unwrap_or("unknown").to_string();
        let inf_state = raw["inference"]["state"].as_str().unwrap_or("unknown").to_string();
        let active_model = raw["inference"]["model_id"].as_str().map(|s| s.to_string());

        let telem: Option<GpuTelemetry> = serde_json::from_value(raw["telemetry"].clone()).ok();
        let gm: Option<GamingModeStatus> = serde_json::from_value(raw["gaming_mode"].clone()).ok();

        let (vram_used, vram_total) = if let Some(ref t) = telem {
            (Some(t.vram_used_mb), Some(t.vram_total_mb))
        } else {
            (None, None)
        };

        Ok(RuntimeStatus {
            core_status,
            inference_status: inf_state,
            active_model,
            vram_allocated_mb: vram_used,
            vram_total_mb: vram_total,
            gpu_telemetry: telem,
            gaming_mode: gm,
        })
    }

    /// List available EXL3 models.
    pub async fn list_models(&self) -> Result<Vec<ModelProfile>, ProxyError> {
        let url = format!("{}/api/v1/models", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<Vec<ModelProfile>>().await?;
        Ok(data)
    }

    /// Request Core to load a specific model in TabbyAPI.
    pub async fn load_model(&self, model_id: &str) -> Result<serde_json::Value, ProxyError> {
        let url = format!("{}/api/v1/models/load", self.core_base_url);
        let body = serde_json::json!({ "model_id": model_id });
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .json(&body)
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<serde_json::Value>().await?;
        Ok(data)
    }

    /// Request Core to unload current model to free GPU VRAM.
    pub async fn unload_model(&self) -> Result<serde_json::Value, ProxyError> {
        let url = format!("{}/api/v1/models/unload", self.core_base_url);
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<serde_json::Value>().await?;
        Ok(data)
    }

    /// Create a new session.
    pub async fn create_session(
        &self,
        title: Option<&str>,
        working_directory: Option<&str>,
    ) -> Result<SessionSummary, ProxyError> {
        let url = format!("{}/api/v1/sessions", self.core_base_url);
        let body = serde_json::json!({
            "title": title.unwrap_or("New Session"),
            "working_directory": working_directory.unwrap_or(".")
        });

        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .json(&body)
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<SessionSummary>().await?;
        Ok(data)
    }

    /// List all chat sessions.
    pub async fn list_sessions(&self) -> Result<Vec<SessionSummary>, ProxyError> {
        let url = format!("{}/api/v1/sessions", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<Vec<SessionSummary>>().await?;
        Ok(data)
    }

    /// Cancel a running turn in a session.
    pub async fn cancel_turn(&self, session_id: &str) -> Result<(), ProxyError> {
        let url = format!("{}/api/v1/sessions/{}/turns/cancel", self.core_base_url, session_id);
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        Ok(())
    }

    /// Query TabbyAPI models directly using supervisor admin key.
    pub async fn check_tabby_models(&self) -> Result<serde_json::Value, ProxyError> {
        let url = format!("{}/v1/models", self.tabby_base_url);
        let res = self
            .client
            .get(&url)
            .header("x-admin-key", self.tabby_admin_key.as_str())
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<serde_json::Value>().await?;
        Ok(data)
    }

    /// Request Core to mint a one-shot capability token after native approval.
    pub async fn mint_approval_token(
        &self,
        tool_name: &str,
        arguments: &serde_json::Value,
    ) -> Result<(String, String), ProxyError> {
        let url = format!("{}/api/v1/approvals/mint", self.core_base_url);
        let body = serde_json::json!({
            "tool_name": tool_name,
            "arguments": arguments,
        });

        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .json(&body)
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let resp: serde_json::Value = res.json().await?;
        let token = resp["one_shot_token"]
            .as_str()
            .or_else(|| resp["token"].as_str())
            .unwrap_or_default()
            .to_string();
        let args_hash = resp["args_hash"].as_str().unwrap_or_default().to_string();
        Ok((token, args_hash))
    }

    /// Fetch real-time NVIDIA GPU telemetry via Core NVML service.
    pub async fn get_gpu_telemetry(&self) -> Result<GpuTelemetry, ProxyError> {
        let url = format!("{}/api/v1/telemetry/gpu", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<GpuTelemetry>().await?;
        Ok(data)
    }

    /// Perform preflight calculation checking if model fits in VRAM.
    pub async fn check_vram_preflight(
        &self,
        request: &PreflightRequest,
    ) -> Result<PreflightResult, ProxyError> {
        let url = format!("{}/api/v1/models/preflight", self.core_base_url);
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .json(request)
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<PreflightResult>().await?;
        Ok(data)
    }

    /// Activate Gaming Mode (one-click turn abort and instant VRAM evacuation).
    pub async fn activate_gaming_mode(&self) -> Result<GamingModeStatus, ProxyError> {
        let url = format!("{}/api/v1/gaming-mode/activate", self.core_base_url);
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<GamingModeStatus>().await?;
        Ok(data)
    }

    /// Deactivate Gaming Mode, restoring normal model load and inference capabilities.
    pub async fn deactivate_gaming_mode(&self) -> Result<GamingModeStatus, ProxyError> {
        let url = format!("{}/api/v1/gaming-mode/deactivate", self.core_base_url);
        let res = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<GamingModeStatus>().await?;
        Ok(data)
    }

    /// Get current Gaming Mode status.
    pub async fn get_gaming_mode_status(&self) -> Result<GamingModeStatus, ProxyError> {
        let url = format!("{}/api/v1/gaming-mode/status", self.core_base_url);
        let res = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.core_bearer_token))
            .send()
            .await?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(ProxyError::CoreError { status, body });
        }

        let data = res.json::<GamingModeStatus>().await?;
        Ok(data)
    }
}
