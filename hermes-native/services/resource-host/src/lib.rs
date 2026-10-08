//! Native ownership primitives, independent of Tauri and GPU code.
//!
//! Children start suspended, enter an owned Windows Job Object, then execute.
//! No port/PID discovery or termination of unowned processes is provided.
//! This library is not yet the authenticated, durable resource coordinator.

#[cfg(windows)]
mod windows;
#[cfg(windows)]
pub use windows::{Worker, WorkerGroup, WorkerSpec};
