//! Native ownership primitives, independent of Tauri and GPU code.
//!
//! Children start suspended, enter an owned Windows Job Object, then execute.
//! No port/PID discovery or termination of unowned processes is provided.
//! This library is not yet the authenticated, durable resource coordinator.

mod frames;
mod readiness;
pub use frames::{FrameError, FrameLimits};
#[cfg(windows)]
mod windows;
pub use readiness::{ReadinessError, ReadinessLimits, ReadinessParser};
#[cfg(windows)]
mod capture;
#[cfg(windows)]
pub use capture::{CaptureLimits, CaptureReport, CapturedWorker, OutputSnapshot};
#[cfg(windows)]
mod framed;
#[cfg(windows)]
pub use framed::FramedWorker;
#[cfg(windows)]
pub use windows::{Worker, WorkerGroup, WorkerSpec};
