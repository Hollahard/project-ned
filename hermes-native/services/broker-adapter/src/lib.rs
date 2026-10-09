//! Hermes Native TabbyAPI Inference Broker Adapter & Profiler Measurement Engine.
//!
//! Provides:
//! - TabbyAPI broker request construction and effective parameter validation
//! - Backend qualification order (EXL3 primary, EXL2 secondary fallback)
//! - KV-cache quantization normalization (FP16, Q4, Q6, Q8)
//! - Real benchmark telemetry tracking (TTFT, TPS, VRAM)
//! - Immutable artifact fingerprinting and measurement cache invalidation

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum BackendType {
    #[serde(rename = "exllamav3")]
    ExLlamaV3,
    #[serde(rename = "exllamav2")]
    ExLlamaV2,
}

impl BackendType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::ExLlamaV3 => "exllamav3",
            Self::ExLlamaV2 => "exllamav2",
        }
    }

    /// Qualification priority: EXL3 is primary (1), EXL2 is fallback (2).
    pub fn priority(&self) -> u8 {
        match self {
            Self::ExLlamaV3 => 1,
            Self::ExLlamaV2 => 2,
        }
    }

    /// Default qualification order.
    pub fn qualification_order() -> Vec<Self> {
        vec![Self::ExLlamaV3, Self::ExLlamaV2]
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum KvCacheMode {
    Fp16,
    Q4,
    Q6,
    Q8,
    Custom(u8, u8),
}

impl KvCacheMode {
    pub fn parse(input: &str) -> Result<Self, String> {
        let trimmed = input.trim().to_uppercase();
        match trimmed.as_str() {
            "FP16" => Ok(Self::Fp16),
            "Q4" | "4,4" => Ok(Self::Q4),
            "Q6" | "6,6" => Ok(Self::Q6),
            "Q8" | "8,8" => Ok(Self::Q8),
            other => {
                if let Some((k, v)) = other.split_once(',') {
                    let k = k.trim().parse::<u8>().map_err(|_| "Invalid K bits".to_string())?;
                    let v = v.trim().parse::<u8>().map_err(|_| "Invalid V bits".to_string())?;
                    if (2..=8).contains(&k) && (2..=8).contains(&v) {
                        return Ok(Self::Custom(k, v));
                    }
                }
                Err(format!("Unsupported cache mode: {}", input))
            }
        }
    }

    pub fn to_payload_string(&self) -> String {
        match self {
            Self::Fp16 => "FP16".to_string(),
            Self::Q4 => "4,4".to_string(),
            Self::Q6 => "6,6".to_string(),
            Self::Q8 => "8,8".to_string(),
            Self::Custom(k, v) => format!("{},{}", k, v),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoadRequest {
    pub model_name: String,
    pub backend: BackendType,
    pub max_seq_len: u32,
    pub max_batch_size: u32,
    pub chunk_size: u32,
    pub cache_size: u32,
    pub cache_mode: KvCacheMode,
    pub draft_mode: String,
}

impl LoadRequest {
    pub fn new(model_name: impl Into<String>, backend: BackendType) -> Self {
        Self {
            model_name: model_name.into(),
            backend,
            max_seq_len: 4096,
            max_batch_size: 1,
            chunk_size: 2048,
            cache_size: 4096,
            cache_mode: KvCacheMode::Q6,
            draft_mode: "disabled".to_string(),
        }
    }

    pub fn with_context(mut self, seq_len: u32, cache_size: u32) -> Self {
        self.max_seq_len = seq_len;
        self.cache_size = cache_size;
        self
    }

    pub fn with_cache_mode(mut self, mode: KvCacheMode) -> Self {
        self.cache_mode = mode;
        self
    }

    pub fn with_batch_size(mut self, batch_size: u32) -> Self {
        self.max_batch_size = batch_size;
        self
    }

    pub fn to_json_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "model_name": self.model_name,
            "backend": self.backend.as_str(),
            "max_seq_len": self.max_seq_len,
            "cache_size": self.cache_size,
            "cache_mode": self.cache_mode.to_payload_string(),
            "max_batch_size": self.max_batch_size,
            "chunk_size": self.chunk_size,
            "draft_model": {
                "draft_mode": self.draft_mode
            }
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EffectiveModelParameters {
    pub model_name: String,
    pub backend: BackendType,
    pub max_seq_len: u32,
    pub max_batch_size: u32,
    pub cache_mode: KvCacheMode,
    pub use_vision: bool,
    pub draft_enabled: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BrokerState {
    Unloaded,
    Loading,
    Ready,
    Unloading,
    Error(String),
}

#[derive(Debug, Clone)]
pub struct BrokerClient {
    state: BrokerState,
    active_params: Option<EffectiveModelParameters>,
    supported_backends: Vec<BackendType>,
}

impl Default for BrokerClient {
    fn default() -> Self {
        Self::new()
    }
}

impl BrokerClient {
    pub fn new() -> Self {
        Self {
            state: BrokerState::Unloaded,
            active_params: None,
            supported_backends: BackendType::qualification_order(),
        }
    }

    pub fn with_supported_backends(backends: Vec<BackendType>) -> Self {
        Self {
            state: BrokerState::Unloaded,
            active_params: None,
            supported_backends: backends,
        }
    }

    pub fn state(&self) -> &BrokerState {
        &self.state
    }

    pub fn active_parameters(&self) -> Option<&EffectiveModelParameters> {
        self.active_params.as_ref()
    }

    /// Selects and qualifies the backend according to priority order.
    pub fn qualify_backend(&self) -> Result<BackendType, String> {
        for candidate in BackendType::qualification_order() {
            if self.supported_backends.contains(&candidate) {
                return Ok(candidate);
            }
        }
        Err("No supported backend available".to_string())
    }

    /// Simulates `/v1/model/load` and validates effective parameter extraction.
    pub fn load_model(&mut self, req: LoadRequest) -> Result<EffectiveModelParameters, String> {
        if !self.supported_backends.contains(&req.backend) {
            return Err(format!("Requested backend '{}' is not supported", req.backend.as_str()));
        }
        if req.cache_size < req.max_seq_len {
            return Err("cache_size must cover max_seq_len".to_string());
        }

        self.state = BrokerState::Loading;

        // Build effective parameters extracted from broker observation
        let effective = EffectiveModelParameters {
            model_name: req.model_name.clone(),
            backend: req.backend,
            max_seq_len: req.max_seq_len,
            max_batch_size: req.max_batch_size,
            cache_mode: req.cache_mode,
            use_vision: false,
            draft_enabled: false,
        };

        self.active_params = Some(effective.clone());
        self.state = BrokerState::Ready;
        Ok(effective)
    }

    /// Simulates `/v1/model/unload` and frees active state.
    pub fn unload_model(&mut self) -> Result<(), String> {
        self.state = BrokerState::Unloading;
        self.active_params = None;
        self.state = BrokerState::Unloaded;
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchmarkTelemetry {
    pub ttft_ms: f64,
    pub tokens_per_second: f64,
    pub vram_used_bytes: u64,
    pub vram_total_bytes: u64,
    pub peak_vram_bytes: u64,
}

impl BenchmarkTelemetry {
    pub fn new(ttft_ms: f64, tokens_per_sec: f64, vram_used: u64, vram_total: u64) -> Self {
        Self {
            ttft_ms,
            tokens_per_second: tokens_per_sec,
            vram_used_bytes: vram_used,
            vram_total_bytes: vram_total,
            peak_vram_bytes: vram_used,
        }
    }

    pub fn vram_utilization_ratio(&self) -> f64 {
        if self.vram_total_bytes == 0 {
            0.0
        } else {
            self.vram_used_bytes as f64 / self.vram_total_bytes as f64
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactFingerprint {
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub template_digest: String,
    pub composite_hash: String,
}

impl ArtifactFingerprint {
    pub fn new(weights: &str, tokenizer: &str, template: &str) -> Self {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        use std::hash::{Hash, Hasher};
        weights.hash(&mut hasher);
        tokenizer.hash(&mut hasher);
        template.hash(&mut hasher);
        let composite = format!("{:016x}", hasher.finish());

        Self {
            weights_digest: weights.to_string(),
            tokenizer_digest: tokenizer.to_string(),
            template_digest: template.to_string(),
            composite_hash: composite,
        }
    }

    pub fn matches(&self, other: &Self) -> bool {
        self.composite_hash == other.composite_hash
            && self.weights_digest == other.weights_digest
            && self.tokenizer_digest == other.tokenizer_digest
            && self.template_digest == other.template_digest
    }
}

#[derive(Debug, Default)]
pub struct ProfilerMeasurementCache {
    entries: HashMap<String, (ArtifactFingerprint, BenchmarkTelemetry)>,
}

impl ProfilerMeasurementCache {
    pub fn new() -> Self {
        Self {
            entries: HashMap::new(),
        }
    }

    pub fn store(&mut self, model_id: &str, fingerprint: ArtifactFingerprint, telemetry: BenchmarkTelemetry) {
        self.entries.insert(model_id.to_string(), (fingerprint, telemetry));
    }

    pub fn get(&self, model_id: &str, current_fingerprint: &ArtifactFingerprint) -> Option<&BenchmarkTelemetry> {
        if let Some((saved_fp, telemetry)) = self.entries.get(model_id) {
            if saved_fp.matches(current_fingerprint) {
                return Some(telemetry);
            }
        }
        None
    }

    /// Checks if the cached fingerprint matches. If not, invalidates and removes the entry.
    /// Returns true if invalidation occurred, false otherwise.
    pub fn invalidate_if_changed(&mut self, model_id: &str, current_fingerprint: &ArtifactFingerprint) -> bool {
        if let Some((saved_fp, _)) = self.entries.get(model_id) {
            if !saved_fp.matches(current_fingerprint) {
                self.entries.remove(model_id);
                return true;
            }
        }
        false
    }

    pub fn invalidate(&mut self, model_id: &str) {
        self.entries.remove(model_id);
    }

    pub fn is_cached(&self, model_id: &str) -> bool {
        self.entries.contains_key(model_id)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}
