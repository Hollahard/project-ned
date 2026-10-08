//! Bounded admission for a Tauri-owned, shared CPU worker generation.
use crate::{ControlError, ControlHost, RetirementReport};
use serde_json::Value;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, TryLockError};
use std::time::{Duration, Instant};

#[derive(Clone)]
pub struct ControlState {
    inner: Arc<Inner>,
}
struct Inner {
    host: Mutex<Option<ControlHost>>,
    retiring: AtomicBool,
    admitted: AtomicBool,
}

/// Acquire before spawning a blocking task. Dropping a cancelled queued task
/// releases admission without executing a worker request.
pub struct ControlPermit {
    inner: Arc<Inner>,
}
impl Drop for ControlPermit {
    fn drop(&mut self) {
        self.inner.admitted.store(false, Ordering::Release);
    }
}
impl ControlPermit {
    pub fn request(self, operation: &str, payload: Value) -> Result<Value, ControlError> {
        let state = ControlState {
            inner: self.inner.clone(),
        };
        state.request_admitted(operation, payload)
    }
}
impl Default for ControlState {
    fn default() -> Self {
        Self::new(None)
    }
}
impl ControlState {
    fn new(host: Option<ControlHost>) -> Self {
        Self {
            inner: Arc::new(Inner {
                host: Mutex::new(host),
                retiring: AtomicBool::new(false),
                admitted: AtomicBool::new(false),
            }),
        }
    }

    /// Host environment selects a local manifest. Missing configuration keeps
    /// the feature unavailable; renderer requests cannot pick a launch path.
    pub fn from_optional_config() -> Result<Self, ControlError> {
        match std::env::var_os("HERMES_NATIVE_CONTROL_CONFIG") {
            None => Ok(Self::default()),
            Some(path) => Self::from_config(Path::new(&path)),
        }
    }

    pub fn from_config(path: &Path) -> Result<Self, ControlError> {
        Ok(Self::new(Some(ControlHost::from_config(path)?)))
    }

    /// At most one request runs; contenders fail immediately instead of
    /// accumulating an unbounded queue on the worker or a blocking mutex.
    pub fn request(&self, operation: &str, payload: Value) -> Result<Value, ControlError> {
        self.try_admit(operation, &payload)?
            .request(operation, payload)
    }

    pub fn try_admit(
        &self,
        operation: &str,
        payload: &Value,
    ) -> Result<ControlPermit, ControlError> {
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(ControlError::retired());
        }
        crate::protocol::validate_request(operation, payload)?;
        if self
            .inner
            .admitted
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(ControlError::application(
                "CONTROL_BUSY",
                "A control operation is already in flight.",
            ));
        }
        let permit = ControlPermit {
            inner: self.inner.clone(),
        };
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(ControlError::retired());
        }
        Ok(permit)
    }

    fn request_admitted(&self, operation: &str, payload: Value) -> Result<Value, ControlError> {
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(ControlError::retired());
        }
        let mut guard = match self.inner.host.try_lock() {
            Ok(guard) => guard,
            Err(TryLockError::WouldBlock) => {
                return Err(ControlError::application(
                    "CONTROL_BUSY",
                    "A control operation is already in flight.",
                ))
            }
            Err(TryLockError::Poisoned(poison)) => {
                self.inner.retiring.store(true, Ordering::Release);
                let mut guard = poison.into_inner();
                if let Some(host) = guard.as_mut() {
                    host.force_retire();
                }
                return Err(ControlError::retired());
            }
        };
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(ControlError::retired());
        }
        let host = guard.as_mut().ok_or_else(ControlError::unavailable)?;
        let result = host.request(operation, payload);
        if self.inner.retiring.load(Ordering::Acquire) {
            let _ = host.retire();
            return Err(ControlError::retired());
        }
        result
    }

    /// Permanently close shared admission, acquire its mutex by the supplied
    /// deadline, then spend only the remaining time on owned retirement.
    /// If an in-flight request outlasts this call it observes the retirement
    /// flag and performs cleanup before releasing its guard.
    pub fn retire(&self, timeout: Duration) -> Result<Option<RetirementReport>, ControlError> {
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(ControlError::invalid)?;
        self.inner.retiring.store(true, Ordering::Release);
        loop {
            match self.inner.host.try_lock() {
                Ok(mut guard) => {
                    return match guard.as_mut() {
                        None => Ok(None),
                        Some(host) => host
                            .retire_with_timeout(deadline.saturating_duration_since(Instant::now()))
                            .cloned()
                            .map(Some),
                    }
                }
                Err(TryLockError::Poisoned(poison)) => {
                    let mut guard = poison.into_inner();
                    if let Some(host) = guard.as_mut() {
                        host.force_retire_with_timeout(
                            deadline.saturating_duration_since(Instant::now()),
                        );
                    }
                    return Err(ControlError::cleanup());
                }
                Err(TryLockError::WouldBlock) => {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        return Err(ControlError::cleanup());
                    }
                    std::thread::sleep(remaining.min(Duration::from_millis(2)));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn absent_configuration_is_unavailable_and_never_launches() {
        let state = ControlState::default();
        assert_eq!(
            state
                .request("runtime.status", serde_json::json!({}))
                .unwrap_err()
                .code,
            "CONTROL_UNAVAILABLE"
        );
        assert!(state.retire(Duration::ZERO).unwrap().is_none());
        assert_eq!(
            state
                .request("runtime.status", serde_json::json!({}))
                .unwrap_err()
                .code,
            "CONTROL_RETIRED"
        );
    }
    #[test]
    fn occupied_mutex_rejects_admission_and_retirement_has_finite_deadline() {
        let state = ControlState::default();
        let guard = state.inner.host.lock().unwrap();
        assert_eq!(
            state
                .request("runtime.status", serde_json::json!({}))
                .unwrap_err()
                .code,
            "CONTROL_BUSY"
        );
        let start = Instant::now();
        assert_eq!(
            state.retire(Duration::from_millis(20)).unwrap_err().code,
            "CONTROL_CLEANUP_INCOMPLETE"
        );
        assert!(start.elapsed() < Duration::from_secs(1));
        drop(guard);
        assert_eq!(
            state
                .request("runtime.status", serde_json::json!({}))
                .unwrap_err()
                .code,
            "CONTROL_RETIRED"
        );
        assert!(state.retire(Duration::ZERO).unwrap().is_none());
    }

    #[test]
    fn blocking_task_admission_is_bounded_before_spawn_and_drop_releases_it() {
        let state = ControlState::default();
        let permit = state
            .try_admit("runtime.status", &serde_json::json!({}))
            .unwrap();
        assert_eq!(
            state
                .try_admit("runtime.status", &serde_json::json!({}))
                .err()
                .unwrap()
                .code,
            "CONTROL_BUSY"
        );
        drop(permit);
        let permit = state
            .try_admit("runtime.status", &serde_json::json!({}))
            .unwrap();
        state.retire(Duration::ZERO).unwrap();
        assert_eq!(
            permit
                .request("runtime.status", serde_json::json!({}))
                .unwrap_err()
                .code,
            "CONTROL_RETIRED"
        );
    }
}
