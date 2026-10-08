//! Window-owned one-shot read-only model artifact inspection. No engine loads.
#![cfg(windows)]
mod config;
mod json;
mod protocol;
mod state;
pub use config::{FilePin, LaunchConfig, SOURCE_FILES};
use serde::Serialize;
pub use state::{CatalogPermit, CatalogState};
#[derive(Debug, Clone, Serialize)]
pub struct CatalogError {
    pub code: &'static str,
    pub message: &'static str,
    pub retired: bool,
}
impl CatalogError {
    fn error(code: &'static str, message: &'static str, retired: bool) -> Self {
        Self {
            code,
            message,
            retired,
        }
    }
    pub fn unavailable() -> Self {
        Self::error(
            "CATALOG_UNAVAILABLE",
            "Model inspection is unavailable.",
            false,
        )
    }
    fn config() -> Self {
        Self::error(
            "CATALOG_CONFIG_INVALID",
            "The host-selected launch receipt is invalid or its source hashes changed.",
            false,
        )
    }
    fn invalid() -> Self {
        Self::error(
            "CATALOG_INVALID_REQUEST",
            "An absolute immediate-child model folder is required.",
            false,
        )
    }
    fn outside() -> Self {
        Self::error(
            "CATALOG_OUTSIDE_GRANT",
            "The model folder is outside the host-granted roots.",
            false,
        )
    }
    fn retired() -> Self {
        Self::error("CATALOG_RETIRED", "The catalog owner is retired.", true)
    }
    fn busy() -> Self {
        Self::error(
            "CATALOG_BUSY",
            "A model inspection is already in flight.",
            false,
        )
    }
    fn transport() -> Self {
        Self::error(
            "CATALOG_TRANSPORT_FAILED",
            "The owned inspector timed out, exited, or lost its transport.",
            false,
        )
    }
    fn protocol() -> Self {
        Self::error(
            "CATALOG_PROTOCOL_FAILED",
            "The owned inspector returned an invalid report.",
            false,
        )
    }
    fn cleanup() -> Self {
        Self::error(
            "CATALOG_CLEANUP_INCOMPLETE",
            "Complete owned process and pipe cleanup was not verified.",
            true,
        )
    }
}
impl std::fmt::Display for CatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for CatalogError {}
#[derive(Debug, Clone, Serialize)]
pub struct Cleanup {
    pub verified: bool,
    pub root_exit_code: u32,
    pub stdout_eof: bool,
    pub stderr_eof: bool,
    pub job_empty: bool,
}
