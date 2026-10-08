//! Host-granted, one-shot metadata inspection for one exact native window lifetime.
use hermes_catalog_host::{CatalogError, CatalogPermit, CatalogState, Cleanup};
use serde_json::Value;
use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tauri::{WebviewWindow, WindowEvent};

pub struct ShellCatalog {
    state: CatalogState,
    owner: AtomicIsize,
    live: Arc<AtomicBool>,
    startup_error: Option<CatalogError>,
    #[cfg(feature = "binding-fixture")]
    delivery: Arc<FixtureDelivery>,
}

pub struct ShellCatalogPermit {
    permit: CatalogPermit,
    live: Arc<AtomicBool>,
    #[cfg(feature = "binding-fixture")]
    delivery: Arc<FixtureDelivery>,
}

#[cfg(feature = "binding-fixture")]
#[derive(Default)]
struct FixtureDelivery {
    armed: AtomicBool,
    held: AtomicBool,
}

fn unavailable() -> CatalogError {
    CatalogError {
        code: "CATALOG_UNAVAILABLE",
        message: "Model inspection is unavailable for this window.",
        retired: false,
    }
}

impl ShellCatalogPermit {
    pub fn inspect(self) -> Result<Value, CatalogError> {
        if !self.live.load(Ordering::Acquire) {
            return Err(unavailable());
        }
        let result = self.permit.inspect();
        #[cfg(feature = "binding-fixture")]
        if result.is_ok() && self.delivery.armed.swap(false, Ordering::AcqRel) {
            // Only delay delivery of a real result after catalog-host already
            // verified child cleanup. This never substitutes model metadata.
            self.delivery.held.store(true, Ordering::Release);
            let deadline = std::time::Instant::now() + Duration::from_secs(5);
            while self.delivery.held.load(Ordering::Acquire) {
                if !self.live.load(Ordering::Acquire) || std::time::Instant::now() >= deadline {
                    self.delivery.held.store(false, Ordering::Release);
                    return Err(unavailable());
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        }
        // A navigation/destruction retires the native generation independently
        // of the blocking worker. Never deliver its result to a later document.
        if !self.live.load(Ordering::Acquire) {
            return Err(unavailable());
        }
        result
    }
}

impl ShellCatalog {
    pub fn new() -> Self {
        let (state, startup_error) = match CatalogState::from_optional_config() {
            Ok(state) => (state, None),
            Err(error) => {
                eprintln!("{}", error.code);
                (CatalogState::default(), Some(error))
            }
        };
        Self {
            state,
            owner: AtomicIsize::new(0),
            live: Arc::new(AtomicBool::new(true)),
            startup_error,
            #[cfg(feature = "binding-fixture")]
            delivery: Arc::new(FixtureDelivery::default()),
        }
    }

    pub fn bind(&self, window: &WebviewWindow) -> Result<(), CatalogError> {
        if window.label() != "main" {
            return Err(unavailable());
        }
        let hwnd = window.hwnd().map_err(|_| unavailable())?.0 as isize;
        self.owner
            .compare_exchange(0, hwnd, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| unavailable())?;
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
        model_path: &str,
    ) -> Result<ShellCatalogPermit, CatalogError> {
        if !self.live.load(Ordering::Acquire)
            || window.label() != "main"
            || !window
                .url()
                .is_ok_and(|url| crate::policy::local_origin(&url))
            || self.owner.load(Ordering::Acquire) == 0
            || window.hwnd().map_err(|_| unavailable())?.0 as isize
                != self.owner.load(Ordering::Acquire)
        {
            return Err(unavailable());
        }
        if let Some(error) = &self.startup_error {
            return Err(error.clone());
        }
        // Admission is before spawn_blocking; the crate permits only one child.
        Ok(ShellCatalogPermit {
            permit: self.state.try_admit(model_path)?,
            live: self.live.clone(),
            #[cfg(feature = "binding-fixture")]
            delivery: self.delivery.clone(),
        })
    }

    pub fn retire(&self) -> Result<Option<Cleanup>, CatalogError> {
        self.live.store(false, Ordering::Release);
        self.state.retire(Duration::from_secs(5))
    }

    #[cfg(feature = "binding-fixture")]
    pub fn fixture_phase(
        &self,
        window: &WebviewWindow,
        phase: &str,
    ) -> Result<Value, CatalogError> {
        if window.label() != "main"
            || window.hwnd().map_err(|_| unavailable())?.0 as isize
                != self.owner.load(Ordering::Acquire)
        {
            return Err(unavailable());
        }
        match phase {
            "catalog-hold-next" if self.live.load(Ordering::Acquire) => {
                self.delivery.armed.store(true, Ordering::Release);
                Ok(serde_json::json!({"armed":true}))
            }
            "catalog-held" => {
                Ok(serde_json::json!({"held":self.delivery.held.load(Ordering::Acquire)}))
            }
            "catalog-release" => {
                self.delivery.held.store(false, Ordering::Release);
                Ok(Value::Null)
            }
            "catalog-inputs" => {
                let root = std::env::var_os("HERMES_NATIVE_CATALOG_FIXTURE_ROOT")
                    .map(std::path::PathBuf::from)
                    .ok_or_else(unavailable)?;
                if !root.is_absolute() || !root.is_dir() {
                    return Err(unavailable());
                }
                Ok(
                    serde_json::json!({ "complete":root.join("complete"), "partial":root.join("partial"), "invalid":root.join("invalid"), "outside":root.parent().ok_or_else(unavailable)?.join("outside") }),
                )
            }
            "catalog-retire" => self
                .retire()
                .map(|receipt| serde_json::json!({"retired":true,"cleanup":receipt})),
            _ => Err(unavailable()),
        }
    }
}
