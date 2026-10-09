//! Hermes Native GPU Resource Authority & Gaming Mode Latch.
//!
//! Provides:
//! - Centralized GPU authority governing all workers (LLM, draft, vision, embeddings, speech, profiler)
//! - Immediate admission barrier returning GATEWAY_BUSY_GAMING_MODE when gaming mode is engaged
//! - Cancellation & drain protocol evacuating in-flight generation and releasing VRAM to 0 baseline
//! - RTX 5090 32 GiB VRAM allocation tracking and cold crash recovery

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub const GATEWAY_BUSY_GAMING_MODE: &str = "GATEWAY_BUSY_GAMING_MODE";
pub const RTX_5090_TOTAL_VRAM_BYTES: u64 = 34_359_738_368; // 32 GiB

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum GpuWorkerType {
    PrimaryLlm,
    DraftModel,
    Vision,
    Embeddings,
    SpeechAudio,
    Profiler,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum GamingModeState {
    Inactive,
    Transitioning,
    Active,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GpuLease {
    pub lease_id: String,
    pub worker: GpuWorkerType,
    pub vram_allocated_bytes: u64,
    pub generation: u64,
    pub active: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GamingModeReport {
    pub vram_freed_bytes: u64,
    pub cancelled_leases: usize,
    pub elapsed_ms: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GpuAuthorityCoordinator {
    pub total_vram_bytes: u64,
    pub allocated_vram_bytes: u64,
    pub gaming_mode: GamingModeState,
    pub generation: u64,
    pub leases: HashMap<String, GpuLease>,
}

impl Default for GpuAuthorityCoordinator {
    fn default() -> Self {
        Self::new(RTX_5090_TOTAL_VRAM_BYTES)
    }
}

impl GpuAuthorityCoordinator {
    pub fn new(total_vram_bytes: u64) -> Self {
        Self {
            total_vram_bytes,
            allocated_vram_bytes: 0,
            gaming_mode: GamingModeState::Inactive,
            generation: 1,
            leases: HashMap::new(),
        }
    }

    pub fn is_gaming_mode_active(&self) -> bool {
        self.gaming_mode == GamingModeState::Active
            || self.gaming_mode == GamingModeState::Transitioning
    }

    pub fn available_vram_bytes(&self) -> u64 {
        self.total_vram_bytes
            .saturating_sub(self.allocated_vram_bytes)
    }

    /// Request GPU worker admission. Fails immediately with GATEWAY_BUSY_GAMING_MODE if Gaming Mode is on.
    pub fn request_admission(
        &mut self,
        worker: GpuWorkerType,
        required_vram_bytes: u64,
    ) -> Result<GpuLease, String> {
        // ADMISSION BARRIER: Immediate queue halt if Gaming Mode is active or transitioning
        if self.is_gaming_mode_active() {
            return Err(format!(
                "{}: Admission barrier active; GPU worker {:?} rejected",
                GATEWAY_BUSY_GAMING_MODE, worker
            ));
        }

        if required_vram_bytes > self.available_vram_bytes() {
            return Err("Insufficient VRAM available for requested worker".to_string());
        }

        self.generation += 1;
        self.allocated_vram_bytes += required_vram_bytes;

        let lease_id = format!("lease-{}-{}", self.generation, self.leases.len() + 1);
        let lease = GpuLease {
            lease_id: lease_id.clone(),
            worker,
            vram_allocated_bytes: required_vram_bytes,
            generation: self.generation,
            active: true,
        };

        self.leases.insert(lease_id, lease.clone());
        Ok(lease)
    }

    /// Releases a completed or cancelled lease, returning VRAM to available pool.
    pub fn release_lease(&mut self, lease_id: &str) -> Result<(), String> {
        if let Some(lease) = self.leases.get_mut(lease_id) {
            if lease.active {
                lease.active = false;
                self.allocated_vram_bytes = self
                    .allocated_vram_bytes
                    .saturating_sub(lease.vram_allocated_bytes);
            }
            Ok(())
        } else {
            Err("Lease not found".to_string())
        }
    }

    /// Activates Gaming Mode: halts all active workers, drains input streams, evacuates 100% of VRAM.
    pub fn activate_gaming_mode(&mut self) -> GamingModeReport {
        let start = std::time::Instant::now();
        self.gaming_mode = GamingModeState::Transitioning;

        let mut cancelled_count = 0;
        let freed_bytes = self.allocated_vram_bytes;

        // Cancellation & Drain Protocol: Cancel all active worker leases
        for lease in self.leases.values_mut() {
            if lease.active {
                lease.active = false;
                cancelled_count += 1;
            }
        }

        // Evacuate all allocated VRAM to 0 baseline
        self.allocated_vram_bytes = 0;
        self.generation += 1;
        self.gaming_mode = GamingModeState::Active;

        let elapsed = start.elapsed().as_secs_f64() * 1000.0;
        GamingModeReport {
            vram_freed_bytes: freed_bytes,
            cancelled_leases: cancelled_count,
            elapsed_ms: elapsed,
        }
    }

    /// Deactivates Gaming Mode, lifting the admission barrier.
    pub fn deactivate_gaming_mode(&mut self) {
        self.gaming_mode = GamingModeState::Inactive;
        self.generation += 1;
    }

    pub fn export_snapshot(&self) -> String {
        serde_json::to_string(self).unwrap_or_default()
    }

    pub fn import_snapshot(json_data: &str) -> Result<Self, String> {
        serde_json::from_str(json_data)
            .map_err(|e| format!("Failed to restore GPU coordinator state: {}", e))
    }
}
