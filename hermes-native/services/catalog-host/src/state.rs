use crate::{config, protocol, CatalogError, Cleanup, LaunchConfig};
use hermes_resource_host::{CaptureReport, FrameLimits, FramedWorker, WorkerGroup};
use serde_json::Value;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
#[derive(Clone)]
pub struct CatalogState {
    inner: Arc<Inner>,
}
struct Inner {
    config: Option<LaunchConfig>,
    retiring: AtomicBool,
    admitted: AtomicBool,
    generation: Mutex<Option<Arc<Generation>>>,
}
struct Generation {
    group: Arc<WorkerGroup>,
    worker: Mutex<Option<Arc<FramedWorker>>>,
    spawn_done: AtomicBool,
    launch_started: AtomicBool,
    done: AtomicBool,
    cleanup: Mutex<Option<Cleanup>>,
}
pub struct CatalogPermit {
    inner: Arc<Inner>,
    generation: Arc<Generation>,
    model: String,
    started: Instant,
}
fn remaining(deadline: Instant) -> Duration {
    deadline.saturating_duration_since(Instant::now())
}
fn record(report: CaptureReport) -> Cleanup {
    Cleanup {
        verified: true,
        root_exit_code: report.exit_code,
        stdout_eof: true,
        stderr_eof: true,
        job_empty: true,
    }
}
impl Default for CatalogState {
    fn default() -> Self {
        Self::new(None)
    }
}
impl CatalogState {
    fn new(config: Option<LaunchConfig>) -> Self {
        Self {
            inner: Arc::new(Inner {
                config,
                retiring: AtomicBool::new(false),
                admitted: AtomicBool::new(false),
                generation: Mutex::new(None),
            }),
        }
    }
    pub fn from_optional_config() -> Result<Self, CatalogError> {
        match std::env::var_os("HERMES_NATIVE_CATALOG_CONFIG") {
            None => Ok(Self::default()),
            Some(path) => Self::from_config(Path::new(&path)),
        }
    }
    pub fn from_config(path: &Path) -> Result<Self, CatalogError> {
        Ok(Self::new(Some(config::load(path)?)))
    }
    pub fn try_admit(&self, model_path: &str) -> Result<CatalogPermit, CatalogError> {
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(CatalogError::retired());
        }
        if self.inner.config.is_none() {
            return Err(CatalogError::unavailable());
        }
        if model_path.is_empty()
            || model_path.len() > 32760
            || model_path.chars().any(char::is_control)
        {
            return Err(CatalogError::invalid());
        }
        if self
            .inner
            .admitted
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(CatalogError::busy());
        }
        let result = (|| {
            let mut slot = self
                .inner
                .generation
                .try_lock()
                .map_err(|_| CatalogError::busy())?;
            if self.inner.retiring.load(Ordering::Acquire) {
                return Err(CatalogError::retired());
            }
            let generation = Arc::new(Generation {
                group: Arc::new(WorkerGroup::new().map_err(|_| CatalogError::transport())?),
                worker: Mutex::new(None),
                spawn_done: AtomicBool::new(false),
                launch_started: AtomicBool::new(false),
                done: AtomicBool::new(false),
                cleanup: Mutex::new(None),
            });
            *slot = Some(generation.clone());
            Ok(CatalogPermit {
                inner: self.inner.clone(),
                generation,
                model: model_path.to_owned(),
                started: Instant::now(),
            })
        })();
        if result.is_err() {
            self.inner.admitted.store(false, Ordering::Release);
        }
        result
    }
    pub fn retire(&self, timeout: Duration) -> Result<Option<Cleanup>, CatalogError> {
        self.inner.retiring.store(true, Ordering::Release);
        let deadline = Instant::now() + timeout.min(Duration::from_secs(5));
        let generation = loop {
            if let Ok(slot) = self.inner.generation.try_lock() {
                break slot.clone();
            }
            if remaining(deadline).is_zero() {
                return Err(CatalogError::cleanup());
            }
            std::thread::sleep(Duration::from_millis(1));
        };
        let Some(generation) = generation else {
            return Ok(None);
        };
        generation
            .group
            .terminate_timeout(43, remaining(deadline))
            .map_err(|_| CatalogError::cleanup())?;
        if !generation.launch_started.load(Ordering::Acquire) {
            return Ok(None);
        }
        generation.finish_retirement(deadline)
    }
}
impl Generation {
    fn finish_retirement(&self, deadline: Instant) -> Result<Option<Cleanup>, CatalogError> {
        loop {
            if let Some(cleanup) = self
                .cleanup
                .lock()
                .map_err(|_| CatalogError::cleanup())?
                .clone()
            {
                return Ok(Some(cleanup));
            }
            let worker = self
                .worker
                .lock()
                .map_err(|_| CatalogError::cleanup())?
                .clone();
            if let Some(worker) = worker {
                let report = self
                    .group
                    .retire_captured(worker.capture(), 43, remaining(deadline))
                    .map_err(|_| CatalogError::cleanup())?;
                let cleanup = record(report);
                *self.cleanup.lock().map_err(|_| CatalogError::cleanup())? = Some(cleanup.clone());
                return Ok(Some(cleanup));
            }
            if self.spawn_done.load(Ordering::Acquire) || self.done.load(Ordering::Acquire) {
                return if self
                    .group
                    .active_count()
                    .map_err(|_| CatalogError::cleanup())?
                    == 0
                {
                    Ok(None)
                } else {
                    Err(CatalogError::cleanup())
                };
            }
            // A launch may have returned a child whose handle is not published
            // yet. An empty Job alone is not root-exit/pipe-EOF proof.
            if remaining(deadline).is_zero() {
                return Err(CatalogError::cleanup());
            }
            std::thread::sleep(remaining(deadline).min(Duration::from_millis(2)));
        }
    }
}
impl CatalogPermit {
    pub fn inspect(self) -> Result<Value, CatalogError> {
        self.generation
            .launch_started
            .store(true, Ordering::Release);
        let config = self
            .inner
            .config
            .as_ref()
            .ok_or_else(CatalogError::unavailable)?;
        let deadline = self.started + config::work(config);
        let result = self.inspect_inner(config, deadline);
        self.generation.spawn_done.store(true, Ordering::Release);
        if result.is_err() {
            let cleanup_deadline = Instant::now() + config::cleanup(config);
            if self
                .generation
                .group
                .terminate_timeout(43, remaining(cleanup_deadline))
                .is_err()
                || self.generation.finish_retirement(cleanup_deadline).is_err()
            {
                self.inner.retiring.store(true, Ordering::Release);
                return Err(CatalogError::cleanup());
            }
        }
        self.generation.done.store(true, Ordering::Release);
        if self.inner.retiring.load(Ordering::Acquire) {
            Err(CatalogError::retired())
        } else {
            result
        }
    }
    fn inspect_inner(
        &self,
        config: &LaunchConfig,
        deadline: Instant,
    ) -> Result<Value, CatalogError> {
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(CatalogError::retired());
        }
        let mut verified = config::verify(config)?;
        let model = config::select_model(&mut verified, &self.model)?;
        if remaining(deadline).is_zero() {
            return Err(CatalogError::transport());
        }
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(CatalogError::retired());
        }
        let mut worker = self
            .generation
            .group
            .spawn_framed(
                &verified.spec,
                FrameLimits {
                    frame_bytes: 65536,
                    queued_frames: 2,
                },
            )
            .map_err(|_| CatalogError::transport())?;
        worker.close_stdin();
        let worker = Arc::new(worker);
        *self
            .generation
            .worker
            .lock()
            .map_err(|_| CatalogError::cleanup())? = Some(worker.clone());
        self.generation.spawn_done.store(true, Ordering::Release);
        if self.inner.retiring.load(Ordering::Acquire) {
            return Err(CatalogError::retired());
        }
        let frame = worker.recv_frame(remaining(deadline)).map_err(|error| {
            if error.kind() == std::io::ErrorKind::InvalidData {
                CatalogError::protocol()
            } else {
                CatalogError::transport()
            }
        })?;
        let result = protocol::response(&frame, &model)?;
        let report = worker
            .capture()
            .finish_capture(remaining(deadline))
            .map_err(|_| CatalogError::transport())?;
        if report.exit_code != 0 {
            return Err(CatalogError::transport());
        }
        match worker.recv_frame(Duration::ZERO) {
            Err(error) if error.kind() == std::io::ErrorKind::UnexpectedEof => {}
            _ => return Err(CatalogError::protocol()),
        }
        while self
            .generation
            .group
            .active_count()
            .map_err(|_| CatalogError::transport())?
            != 0
        {
            if remaining(deadline).is_zero() {
                return Err(CatalogError::transport());
            }
            std::thread::sleep(remaining(deadline).min(Duration::from_millis(2)));
        }
        self.generation
            .group
            .terminate_timeout(0, remaining(deadline))
            .map_err(|_| CatalogError::transport())?;
        *self
            .generation
            .cleanup
            .lock()
            .map_err(|_| CatalogError::cleanup())? = Some(record(report));
        if remaining(deadline).is_zero() {
            return Err(CatalogError::transport());
        }
        Ok(result)
    }
}
impl Drop for CatalogPermit {
    fn drop(&mut self) {
        // Cancellation before dispatch cannot leave a launchable queued generation.
        let _ = self.generation.group.terminate_timeout(43, Duration::ZERO);
        self.generation.spawn_done.store(true, Ordering::Release);
        self.generation.done.store(true, Ordering::Release);
        self.inner.admitted.store(false, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use hermes_resource_host::WorkerSpec;
    use std::collections::BTreeMap;
    #[test]
    fn close_before_worker_publication_keeps_fence_and_withholds_cleanup_proof() {
        let group = Arc::new(WorkerGroup::new().unwrap());
        let generation = Arc::new(Generation {
            group: group.clone(),
            worker: Mutex::new(None),
            spawn_done: AtomicBool::new(false),
            launch_started: AtomicBool::new(true),
            done: AtomicBool::new(false),
            cleanup: Mutex::new(None),
        });
        let state = CatalogState::default();
        *state.inner.generation.lock().unwrap() = Some(generation.clone());
        assert_eq!(
            state.retire(Duration::ZERO).unwrap_err().code,
            "CATALOG_CLEANUP_INCOMPLETE"
        );
        let spec = WorkerSpec {
            executable: Path::new("C:\\missing.exe").to_owned(),
            working_directory: Path::new("C:\\").to_owned(),
            environment: BTreeMap::new(),
            arguments: Vec::new(),
        };
        assert_eq!(
            group.spawn(&spec).err().unwrap().kind(),
            std::io::ErrorKind::PermissionDenied
        );
        generation.spawn_done.store(true, Ordering::Release);
        assert!(state.retire(Duration::ZERO).unwrap().is_none());
        assert_eq!(
            state.try_admit("C:\\models\\model").err().unwrap().code,
            "CATALOG_RETIRED"
        );
    }
}
