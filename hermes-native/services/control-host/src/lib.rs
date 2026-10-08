//! Owned CPU control-worker generation with a finite public operation surface.
#![cfg(windows)]
mod config;
mod json;
mod protocol;
mod state;
pub use config::{FilePin, LaunchConfig, SOURCE_FILES};
pub use protocol::OPERATIONS;
pub use state::{ControlPermit, ControlState};

use hermes_resource_host::{CaptureReport, FrameLimits, FramedWorker, WorkerGroup};
use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Serialize)]
pub struct ControlError {
    pub code: &'static str,
    pub message: &'static str,
    pub retired: bool,
}
impl std::fmt::Display for ControlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for ControlError {}
impl ControlError {
    fn application(code: &'static str, message: &'static str) -> Self {
        Self {
            code,
            message,
            retired: false,
        }
    }
    fn config() -> Self {
        Self::application(
            "CONTROL_CONFIG_INVALID",
            "The host-selected control configuration is invalid or its source hashes changed.",
        )
    }
    fn protocol() -> Self {
        Self {
            code: "CONTROL_PROTOCOL_FAILED",
            message: "The owned control worker returned an invalid response.",
            retired: true,
        }
    }
    fn invalid() -> Self {
        Self::application(
            "CONTROL_INVALID_REQUEST",
            "The control request shape or size is invalid.",
        )
    }
    pub fn unavailable() -> Self {
        Self::application(
            "CONTROL_UNAVAILABLE",
            "This control operation is unavailable.",
        )
    }
    fn retired() -> Self {
        Self {
            code: "CONTROL_RETIRED",
            message: "The owned control generation is retired.",
            retired: true,
        }
    }
    fn transport() -> Self {
        Self {
            code: "CONTROL_TRANSPORT_FAILED",
            message: "The owned control worker timed out, exited, or lost its transport.",
            retired: true,
        }
    }
    fn cleanup() -> Self {
        Self { code: "CONTROL_CLEANUP_INCOMPLETE", message: "The control generation is retired but complete process and pipe cleanup was not verified.", retired: true }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct RetirementReport {
    pub root_exit_code: u32,
    pub job_empty: bool,
    pub stdout_eof: bool,
    pub stderr_eof: bool,
    pub cooperative: bool,
}

pub struct ControlHost {
    group: Option<WorkerGroup>,
    worker: FramedWorker,
    next_id: u32,
    request_timeout: Duration,
    shutdown_timeout: Duration,
    retired: bool,
    cleanup: Option<RetirementReport>,
}

impl ControlHost {
    pub fn from_config(path: &Path) -> Result<Self, ControlError> {
        let verified = config::load(path)?;
        let group = WorkerGroup::new().map_err(|_| ControlError::transport())?;
        let worker = group
            .spawn_framed(&verified.spec, FrameLimits::default())
            .map_err(|_| ControlError::transport())?;
        let mut host = Self {
            group: Some(group),
            worker,
            next_id: 1,
            request_timeout: verified.request,
            shutdown_timeout: verified.shutdown,
            retired: false,
            cleanup: None,
        };
        let start = Instant::now();
        match host.worker.recv_frame(verified.startup) {
            Ok(frame)
                if protocol::hello(&frame)
                    && host
                        .worker
                        .capture()
                        .worker()
                        .wait_timeout(Duration::ZERO)
                        .is_ok_and(|code| code.is_none()) => {}
            _ => {
                host.force_retire();
                return Err(ControlError::transport());
            }
        }
        let remaining = verified.startup.saturating_sub(start.elapsed());
        if let Err(error) = host.exchange("service.describe", &serde_json::json!({}), remaining) {
            host.force_retire();
            return Err(error);
        }
        Ok(host)
    }

    pub fn request(&mut self, operation: &str, params: Value) -> Result<Value, ControlError> {
        if self.retired {
            return Err(ControlError::retired());
        }
        protocol::validate_request(operation, &params)?;
        // Reserve an ID for the owner's final shutdown. A retired generation
        // never auto-restarts or retries an uncertain mutation.
        if self.next_id >= 4096 {
            self.force_retire();
            return Err(ControlError::retired());
        }
        let result = self.exchange(operation, &params, self.request_timeout);
        if result.as_ref().is_err_and(|error| error.retired) {
            self.force_retire();
        }
        result
    }

    fn exchange(
        &mut self,
        operation: &str,
        params: &Value,
        timeout: Duration,
    ) -> Result<Value, ControlError> {
        // No reply is expected between requests. Detect already-buffered
        // unsolicited/duplicate messages before admitting another mutation.
        self.check_idle_output(false)?;
        let id = format!("r{}", self.next_id);
        self.next_id += 1;
        let frame =
            serde_json::to_vec(&serde_json::json!({"id":id,"method":operation,"params":params}))
                .map_err(|_| ControlError::invalid())?;
        if frame.len() >= 65_536 {
            return Err(ControlError::invalid());
        }
        let start = Instant::now();
        self.worker
            .write_frame(&frame, timeout)
            .map_err(|_| ControlError::transport())?;
        let response = self
            .worker
            .recv_frame(timeout.saturating_sub(start.elapsed()))
            .map_err(|_| ControlError::transport())?;
        let result = protocol::response(&response, &id, operation, params);
        self.check_idle_output(operation == "service.shutdown")?;
        if operation != "service.shutdown"
            && self
                .worker
                .capture()
                .worker()
                .wait_timeout(Duration::ZERO)
                .map_err(|_| ControlError::transport())?
                .is_some()
        {
            return Err(ControlError::transport());
        }
        result
    }

    fn check_idle_output(&self, allow_eof: bool) -> Result<(), ControlError> {
        match self.worker.recv_frame(Duration::ZERO) {
            Err(error) if error.kind() == std::io::ErrorKind::TimedOut => Ok(()),
            Err(error) if allow_eof && error.kind() == std::io::ErrorKind::UnexpectedEof => Ok(()),
            _ => Err(ControlError::protocol()),
        }
    }

    pub fn is_retired(&self) -> bool {
        self.retired
    }
    pub fn cleanup_report(&self) -> Option<&RetirementReport> {
        self.cleanup.as_ref()
    }

    pub fn retire(&mut self) -> Result<&RetirementReport, ControlError> {
        self.retire_with_timeout(self.shutdown_timeout)
    }

    pub fn retire_with_timeout(
        &mut self,
        timeout: Duration,
    ) -> Result<&RetirementReport, ControlError> {
        let timeout = timeout.min(self.shutdown_timeout);
        if self.cleanup.is_some() {
            return self.cleanup.as_ref().ok_or_else(ControlError::cleanup);
        }
        let retirement_started = Instant::now();
        if !self.retired {
            let start = Instant::now();
            let grace = timeout / 2;
            let acknowledged = self
                .exchange("service.shutdown", &serde_json::json!({}), grace)
                .is_ok();
            self.retired = true;
            self.worker.close_stdin();
            if acknowledged {
                if let Ok(report) = self
                    .worker
                    .capture()
                    .finish_capture(grace.saturating_sub(start.elapsed()))
                {
                    if report.exit_code == 0
                        && self.check_idle_output(true).is_ok()
                        && self.wait_job_empty(grace.saturating_sub(start.elapsed()))
                    {
                        self.record(report, true);
                        self.group.take();
                        return Ok(self.cleanup.as_ref().expect("cleanup recorded"));
                    }
                }
            }
        }
        self.force_retire_with_timeout(timeout.saturating_sub(retirement_started.elapsed()));
        self.cleanup.as_ref().ok_or_else(ControlError::cleanup)
    }

    fn force_retire(&mut self) {
        self.force_retire_with_timeout(self.shutdown_timeout);
    }

    fn wait_job_empty(&self, timeout: Duration) -> bool {
        let started = Instant::now();
        loop {
            match self.group.as_ref().map(WorkerGroup::active_count) {
                Some(Ok(0)) => return true,
                Some(Ok(_)) => {}
                _ => return false,
            }
            let remaining = timeout.saturating_sub(started.elapsed());
            if remaining.is_zero() {
                return false;
            }
            std::thread::sleep(remaining.min(Duration::from_millis(2)));
        }
    }

    fn force_retire_with_timeout(&mut self, timeout: Duration) {
        self.retired = true;
        self.worker.close_stdin();
        if let Some(group) = self.group.take() {
            if let Ok(report) = group.retire_captured(self.worker.capture(), 29, timeout) {
                self.record(report, false);
            }
            // Even failed cleanup drops the final owning Job handle. Failure
            // remains unverified; no successful cleanup claim is synthesized.
        }
    }

    fn record(&mut self, report: CaptureReport, cooperative: bool) {
        self.cleanup = Some(RetirementReport {
            root_exit_code: report.exit_code,
            job_empty: true,
            stdout_eof: true,
            stderr_eof: true,
            cooperative,
        });
    }
}

impl Drop for ControlHost {
    fn drop(&mut self) {
        // Drop never makes a protocol request or blocks. Owning Job close is the
        // final lifetime backstop; call retire() for verified graceful cleanup.
        self.retired = true;
        self.worker.close_stdin();
        self.group.take();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn strict_json_rejects_duplicate_keys_at_every_depth() {
        for frame in [
            br#"{"id":"r1","id":"r1"}"#.as_slice(),
            br#"{"result":{"a":1,"a":2}}"#,
            b"{} trailing",
            b"{\"x\":NaN}",
        ] {
            assert!(json::decode(frame).is_err());
        }
    }
    #[test]
    fn renderer_cannot_choose_internal_methods_or_unknown_fields() {
        assert!(protocol::validate_request("service.shutdown", &serde_json::json!({})).is_err());
        assert!(protocol::validate_request("service.describe", &serde_json::json!({})).is_err());
        assert!(protocol::validate_request(
            "runtime.status",
            &serde_json::json!({"secret":"not forwarded"})
        )
        .is_err());
    }
    #[test]
    fn response_rejects_unknown_fields_ids_and_credential_keys() {
        for response in [br#"{"id":"r2","result":{}}"#.as_slice(), br#"{"id":"r1","result":{},"token":"x"}"#,
            br#"{"id":"r1","result":{"state":"detached","runtime_attached":false,"admission_allowed":false,"active_profile":null,"engine_observed":false,"api_key":"x"}}"#] {
            assert!(protocol::response(response,"r1","runtime.status",&serde_json::json!({})).unwrap_err().retired);
        }
    }
}
