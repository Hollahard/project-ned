//! Supervisor runtime coordinator and lifecycle state machine.
//!
//! Invariants:
//! 1. Lifecycle states: Uninitialized -> Starting -> Ready -> ShuttingDown -> Stopped.
//! 2. Zero zombie processes: On drop or stop, Job Object termination guarantees
//!    cleanup of every child and descendant process.
//! 3. All tokens are generated per-launch and held strictly in-memory.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::{info, warn};
use uuid::Uuid;

use crate::approvals::ApprovalManager;
use crate::processes::{ProcessError, ProcessManager};
use crate::proxy::CoreProxy;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LifecycleStatus {
    Uninitialized,
    Starting,
    Ready,
    Degraded,
    ShuttingDown,
    Stopped,
}

#[derive(Debug, Clone)]
pub struct SupervisorConfig {
    pub core_root: PathBuf,
    pub core_python: PathBuf,
    pub core_port: u16,
    pub tabby_root: Option<PathBuf>,
    pub tabby_python: Option<PathBuf>,
    pub tabby_port: u16,
    pub tabby_admin_key: String,
    pub token_secret: String,
}

impl Default for SupervisorConfig {
    fn default() -> Self {
        Self {
            core_root: PathBuf::from(r"G:\Project_Ned\services\core"),
            core_python: PathBuf::from(r"G:\Project_Ned\.venv\Scripts\python.exe"),
            core_port: 8000,
            tabby_root: Some(PathBuf::from(r"G:\Project_Ned\runtime\tabbyAPI")),
            tabby_python: Some(PathBuf::from(r"G:\Project_Ned\runtime\tabbyAPI\.venv\Scripts\python.exe")),
            tabby_port: 5000,
            tabby_admin_key: "admin".to_string(),
            token_secret: Uuid::new_v4().to_string(),
        }
    }
}

pub struct SupervisorRuntime {
    config: SupervisorConfig,
    status: Arc<RwLock<LifecycleStatus>>,
    process_manager: Option<Arc<ProcessManager>>,
    proxy: Option<Arc<CoreProxy>>,
    approvals: Option<Arc<ApprovalManager>>,
    core_pid: Option<u32>,
    tabby_pid: Option<u32>,
}

impl SupervisorRuntime {
    pub fn new(config: SupervisorConfig) -> Self {
        Self {
            config,
            status: Arc::new(RwLock::new(LifecycleStatus::Uninitialized)),
            process_manager: None,
            proxy: None,
            approvals: None,
            core_pid: None,
            tabby_pid: None,
        }
    }

    pub async fn current_status(&self) -> LifecycleStatus {
        *self.status.read().await
    }

    /// Starts child processes and initializes the proxy.
    pub async fn start(&mut self) -> Result<(), ProcessError> {
        {
            let mut st = self.status.write().await;
            *st = LifecycleStatus::Starting;
        }

        info!("Starting Project Friday Supervisor...");

        // Generate ephemeral Bearer token for Core API
        let bearer_token = Uuid::new_v4().to_string();

        // 1. Initialize Windows Job Object
        let proc_mgr = Arc::new(ProcessManager::new()?);

        // 2. Spawn Tabby sidecar if configured and directory exists
        if let (Some(tabby_dir), Some(tabby_py)) = (&self.config.tabby_root, &self.config.tabby_python) {
            if tabby_dir.exists() && tabby_py.exists() {
                match proc_mgr.spawn_tabby(
                    tabby_dir,
                    tabby_py,
                    &self.config.tabby_admin_key,
                    self.config.tabby_port,
                ) {
                    Ok(pid) => {
                        self.tabby_pid = Some(pid);
                        info!("Tabby sidecar launched with PID {}", pid);
                    }
                    Err(e) => {
                        warn!("Could not launch Tabby sidecar: {}. Core will run in mock/unconnected mode.", e);
                    }
                }
            }
        }

        // 3. Spawn Core service
        let core_pid = proc_mgr.spawn_core(
            &self.config.core_root,
            &self.config.core_python,
            &bearer_token,
            self.config.core_port,
        )?;
        self.core_pid = Some(core_pid);

        // 4. Initialize Proxy and Approvals
        let proxy = Arc::new(CoreProxy::new(
            self.config.core_port,
            bearer_token.clone(),
            self.config.tabby_port,
            self.config.tabby_admin_key.clone(),
        ));

        let approvals = Arc::new(ApprovalManager::new(self.config.token_secret.clone(), 120));

        self.process_manager = Some(proc_mgr);
        self.proxy = Some(proxy.clone());
        self.approvals = Some(approvals);

        // 5. Poll for readiness with timeout (15 seconds)
        info!("Waiting for Core service readiness on port {}...", self.config.core_port);
        let mut healthy = false;
        for _ in 0..30 {
            tokio::time::sleep(Duration::from_millis(500)).await;
            if let Ok(health) = proxy.check_health().await {
                if health.status == "ok" {
                    healthy = true;
                    break;
                }
            }
        }

        let mut st = self.status.write().await;
        if healthy {
            *st = LifecycleStatus::Ready;
            info!("Project Friday Supervisor is READY and healthy.");
        } else {
            *st = LifecycleStatus::Degraded;
            warn!("Core service did not respond to health checks in time. Status set to DEGRADED.");
        }

        Ok(())
    }

    /// Stops all child processes cleanly and frees all resources.
    pub async fn stop(&mut self) {
        {
            let mut st = self.status.write().await;
            *st = LifecycleStatus::ShuttingDown;
        }

        info!("Shutting down Project Friday Supervisor and all child processes...");

        if let Some(mgr) = &self.process_manager {
            mgr.kill_all();
        }

        self.core_pid = None;
        self.tabby_pid = None;
        self.process_manager = None;
        self.proxy = None;

        {
            let mut st = self.status.write().await;
            *st = LifecycleStatus::Stopped;
        }
        info!("Supervisor shutdown complete. Zero child processes remaining.");
    }

    pub fn proxy(&self) -> Option<Arc<CoreProxy>> {
        self.proxy.clone()
    }

    pub fn approvals(&self) -> Option<Arc<ApprovalManager>> {
        self.approvals.clone()
    }
}

impl Drop for SupervisorRuntime {
    fn drop(&mut self) {
        if let Some(mgr) = &self.process_manager {
            mgr.kill_all();
        }
    }
}
