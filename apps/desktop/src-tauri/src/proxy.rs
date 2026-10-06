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
pub struct RuntimeStatus {
    pub core_status: String,
    pub inference_status: String,
    pub active_model: Option<String>,
    pub vram_allocated_mb: Option<f64>,
    pub vram_total_mb: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionSummary {
    pub id: String,
    pub title: String,
    pub created_at: String,
    pub updated_at: String,
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
            client: Client::builder().build().unwrap(),
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

        let data = res.json::<RuntimeStatus>().await?;
        Ok(data)
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
            "working_directory": working_directory
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
        let token = resp["token"].as_str().unwrap_or_default().to_string();
        let args_hash = resp["args_hash"].as_str().unwrap_or_default().to_string();
        Ok((token, args_hash))
    }
}
