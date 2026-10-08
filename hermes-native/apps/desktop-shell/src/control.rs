//! One host-selected CPU worker, owned for the exact main native window lifetime.
use hermes_control_host::{ControlError, ControlPermit, ControlState, RetirementReport};
use serde_json::Value;
use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tauri::{WebviewWindow, WindowEvent};

pub struct ShellControl {
    state: ControlState,
    owner: AtomicIsize,
    live: Arc<AtomicBool>,
    startup_error: Option<ControlError>,
    #[cfg(feature = "binding-fixture")]
    pub started: bool,
}

impl ShellControl {
    pub fn new() -> Self {
        #[cfg(feature = "binding-fixture")]
        let configured = std::env::var_os("HERMES_NATIVE_CONTROL_CONFIG").is_some();
        let (state, startup_error) = match ControlState::from_optional_config() {
            Ok(state) => (state, None),
            Err(error) => {
                eprintln!("{}", error.code);
                (ControlState::default(), Some(error))
            }
        };
        Self {
            state,
            owner: AtomicIsize::new(0),
            live: Arc::new(AtomicBool::new(true)),
            #[cfg(feature = "binding-fixture")]
            started: configured && startup_error.is_none(),
            startup_error,
        }
    }

    pub fn bind(&self, window: &WebviewWindow) -> Result<(), ControlError> {
        if window.label() != "main" {
            return Err(ControlError::unavailable());
        }
        let hwnd = window.hwnd().map_err(|_| ControlError::unavailable())?.0 as isize;
        self.owner
            .compare_exchange(0, hwnd, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| ControlError::unavailable())?;
        let state = self.state.clone();
        let live = self.live.clone();
        window.on_window_event(move |event| {
            if matches!(event, WindowEvent::Destroyed) {
                live.store(false, Ordering::Release);
                if let Err(error) = state.retire(Duration::from_secs(5)) {
                    eprintln!("{}", error.code);
                }
            }
        });
        Ok(())
    }

    pub fn admit(
        &self,
        window: &WebviewWindow,
        operation: &str,
        payload: &Value,
    ) -> Result<ControlPermit, ControlError> {
        if !self.live.load(Ordering::Acquire)
            || self.owner.load(Ordering::Acquire) == 0
            || window.hwnd().map_err(|_| ControlError::unavailable())?.0 as isize
                != self.owner.load(Ordering::Acquire)
        {
            return Err(ControlError::unavailable());
        }
        if let Some(error) = &self.startup_error {
            return Err(error.clone());
        }
        // Admission happens BEFORE enqueueing a blocking task, so at most one
        // payload/task can be queued or executing for this worker generation.
        self.state.try_admit(operation, payload)
    }

    pub fn retire(&self) -> Result<Option<RetirementReport>, ControlError> {
        self.live.store(false, Ordering::Release);
        let report = self.state.retire(Duration::from_secs(5))?;
        // A failed startup has no successful retirement receipt to inherit
        // from the empty fallback state, even if no worker may have launched.
        if let Some(error) = &self.startup_error {
            return Err(error.clone());
        }
        Ok(report)
    }
}
