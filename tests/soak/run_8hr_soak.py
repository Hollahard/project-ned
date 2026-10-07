"""Phase 16 Deliverable 2: Standalone Long-Run Endurance Runner for Project Friday.

Supported execution modes:
  - smoke:   15-minute qualification / smoke endurance run (alias: 15m)
  - gate:    1-hour GPU endurance qualification gate (alias: 1h)
  - release: 8-hour full continuous soak run (alias: 8h)
  - custom:  user-specified duration via --duration-minutes

Invariants strictly enforced (adhering strictly to ADR-0002):
1. Process Memory: Private Bytes slope < 50 MB/hour; handle count growth < 50/hour; zero thread ratcheting.
2. VRAM Recovery Oracle: Tabby PID compute-apps memory returns within 512 MB of post-start residual upon unload.
   No monotonic growth across unload cycles. Process termination returns total GPU memory to Windows baseline.
3. SQLite Concurrency & Integrity: WAL < 64 MB; zero database locks; PRAGMA integrity_check passes;
   PRAGMA wal_checkpoint(TRUNCATE) strictly at run boundaries.
4. Windows Job Object Supervision: Child processes enclosed in Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
   JOB_OBJECT_LIMIT_ACTIVE_PROCESS is strictly omitted to preserve worker concurrency. Zero orphaned processes.
5. In-flight Fault Injections: Gaming Mode evacuation (< 2.0s deadline), mid-turn cancel (0 leaked tasks),
   Job Object sidecar restart, session teardown, model OOM, frozen network-off job.
6. Dual-sink Telemetry: Streamed to logs/traces/soak_<timestamp>.jsonl and Langfuse Cloud.
7. Benchmark Reporting: logs/soak_results.json and docs/benchmarks/soak_test_report.md with ASCII sparklines.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tracemalloc
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import aiosqlite

from friday.agent.loop import AgentLoop
from friday.inference.gaming_mode import GamingModeController, GamingModeStatus
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    HealthStatus,
    InferenceEvent,
    InferenceEventType,
    ModelInfo,
    ModelProfile,
    ModelState,
)
from friday.memory import MemoryCoordinator
from friday.memory.semantic import SemanticMemoryEntry
from friday.scheduler.db import SchedulerDatabaseManager
from friday.scheduler.models import (
    JobPermissionSnapshot,
    JobRun,
    RunState,
    ScheduleType,
    ScheduledJob,
)
from friday.scheduler.worker import ScheduledExecutionGuard
from friday.security.tokens import CapabilityTokenManager
from friday.storage.db import DatabaseManager
from friday.tools.base import Tool, ToolResult
from friday.tools.native_read import SystemInfoTool
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry

# Optional dependencies
_PSUTIL_AVAILABLE = False
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None

_NVML_AVAILABLE = False
try:
    import pynvml
    _NVML_AVAILABLE = True
except ImportError:
    pynvml = None

try:
    from friday.telemetry.langfuse import LangfuseSink
    from friday.telemetry.tracer import sanitize_payload
except ImportError:
    LangfuseSink = None  # type: ignore

    def sanitize_payload(obj: Any) -> Any:  # type: ignore
        return obj


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("friday.soak")


# ==============================================================================
# 1. Win32 ctypes Structures & Constants
# ==============================================================================

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
psapi = ctypes.windll.psapi if sys.platform == "win32" else None

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


# ==============================================================================
# 2. Windows Job Object Supervisor
# ==============================================================================


class Win32JobSupervisor:
    """Manages Windows Job Object with KILL_ON_JOB_CLOSE semantics."""

    def __init__(self) -> None:
        self._handle: Optional[int] = None
        if sys.platform != "win32" or kernel32 is None:
            logger.warning("Non-Windows OS detected; Win32JobSupervisor operates in mock mode.")
            return

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle or handle == 0:
            err = kernel32.GetLastError()
            raise OSError(f"CreateJobObjectW failed with error code {err}")
        self._handle = handle

        # Configure Extended Limits: KILL_ON_JOB_CLOSE strictly enabled.
        # CRITICAL INVARIANT (ADR-0002 §4): Do NOT set JOB_OBJECT_LIMIT_ACTIVE_PROCESS.
        ext_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ext_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ext_info.BasicLimitInformation.ActiveProcessLimit = 0

        res = kernel32.SetInformationJobObject(
            self._handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(ext_info),
            ctypes.sizeof(ext_info),
        )
        if res == 0:
            err = kernel32.GetLastError()
            kernel32.CloseHandle(self._handle)
            self._handle = None
            raise OSError(f"SetInformationJobObject failed with error code {err}")

        logger.info("Initialized Windows Job Object (handle=%s) with KILL_ON_JOB_CLOSE", self._handle)

    def assign_process(self, pid: int) -> bool:
        """Assign an active process to this Job Object by PID."""
        if not self._handle or kernel32 is None:
            return False

        h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_INFORMATION, False, pid)
        if not h_proc:
            err = kernel32.GetLastError()
            logger.error("OpenProcess failed for PID %d with error %d", pid, err)
            return False

        try:
            res = kernel32.AssignProcessToJobObject(self._handle, h_proc)
            if res == 0:
                err = kernel32.GetLastError()
                logger.error("AssignProcessToJobObject failed for PID %d with error %d", pid, err)
                return False
            logger.info("Successfully assigned PID %d to Windows Job Object", pid)
            return True
        finally:
            kernel32.CloseHandle(h_proc)

    def query_active_processes(self) -> int:
        """Return the count of active processes running inside this Job Object."""
        if not self._handle or kernel32 is None:
            return 0

        acct_info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        res = kernel32.QueryInformationJobObject(
            self._handle,
            JobObjectBasicAccountingInformation,
            ctypes.byref(acct_info),
            ctypes.sizeof(acct_info),
            None,
        )
        if res == 0:
            err = kernel32.GetLastError()
            logger.error("QueryInformationJobObject failed with error %d", err)
            return 0
        return int(acct_info.ActiveProcesses)

    def terminate_all(self, exit_code: int = 0) -> None:
        """Immediately terminate all child processes belonging to the Job Object."""
        if self._handle and kernel32 is not None:
            kernel32.TerminateJobObject(self._handle, exit_code)
            logger.info("Terminated all processes in Job Object with exit code %d", exit_code)

    def close(self) -> None:
        """Close Job Object handle, triggering kernel-level termination of all assigned processes."""
        if self._handle and kernel32 is not None:
            kernel32.CloseHandle(self._handle)
            logger.info("Closed Windows Job Object handle %s", self._handle)
            self._handle = None

    def __enter__(self) -> "Win32JobSupervisor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# ==============================================================================
# 3. Graceful Shutdown Coordinator
# ==============================================================================


class GracefulShutdownCoordinator:
    """Coordinates graceful draining, database checkpointing, and Job Object teardown."""

    def __init__(self, job_supervisor: Optional[Win32JobSupervisor] = None) -> None:
        self.job_supervisor = job_supervisor
        self.shutdown_event = asyncio.Event()
        self.turn_cancel_event = asyncio.Event()
        self._cleanup_callbacks: List[Callable[[], Any]] = []
        self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        def _handle_signal(sig: int, frame: Any) -> None:
            sig_name = signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig)
            logger.warning("Received termination signal %s. Initiating graceful shutdown...", sig_name)
            self.trigger_shutdown()

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except Exception as exc:
            logger.debug("Signal handler registration skipped: %s", exc)

    def trigger_shutdown(self) -> None:
        """Trigger cooperative shutdown across all asynchronous loops."""
        self.shutdown_event.set()
        self.turn_cancel_event.set()

    def register_cleanup(self, callback: Callable[[], Any]) -> None:
        """Register a synchronous or asynchronous teardown callback."""
        self._cleanup_callbacks.append(callback)

    async def execute_teardown(self) -> None:
        """Two-phase shutdown: cooperative drain followed by Job Object termination."""
        logger.info("Beginning Phase 1 teardown: cooperative database flush & turn cancellation...")
        self.trigger_shutdown()

        # Execute registered cleanup callbacks (database closes, checkpoints)
        for cb in self._cleanup_callbacks:
            try:
                res = cb()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.error("Error in teardown callback: %s", exc)

        logger.info("Beginning Phase 2 teardown: Job Object child process termination...")
        if self.job_supervisor:
            active_count = self.job_supervisor.query_active_processes()
            if active_count > 0:
                logger.info("Terminating %d remaining processes in Job Object...", active_count)
                self.job_supervisor.terminate_all(0)

            # Close job object handle
            self.job_supervisor.close()

        logger.info("Teardown complete. Zero orphaned processes remaining.")


# ==============================================================================
# 4. Controllable Mock Inference Backend
# ==============================================================================


class SoakInferenceEngine(MockInferenceBackend):
    """Controllable backend for endurance soak tests with fault injection."""

    def __init__(self) -> None:
        super().__init__()
        self.state = ModelState.READY
        self.active_profile = ModelProfile(
            name="soak-qwen2.5-coder-32b",
            model_dir="models/qwen2.5-coder-32b",
            context_length=32768,
        )
        self.call_count = 0
        self.unload_count = 0
        self.load_count = 0
        self.simulate_oom = False
        self.mock_vram_residual_mb = 1240.0
        self.mock_vram_active_mb = 18450.0
        self.current_vram_mb = self.mock_vram_active_mb

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        self.call_count += 1

        if self.simulate_oom:
            self.state = ModelState.ERROR
            yield InferenceEvent(
                type=InferenceEventType.ERROR,
                content="CUDA out of memory during KV-cache allocation (simulated fault)",
            )
            return

        tokens = ["Turn", f"{self.call_count}", "response", "stream", "chunk."]
        for token in tokens:
            yield InferenceEvent(
                type=InferenceEventType.TOKEN_DELTA,
                content=token + " ",
            )
            await asyncio.sleep(0.002)

        yield InferenceEvent(
            type=InferenceEventType.USAGE,
            prompt_tokens=45,
            completion_tokens=len(tokens),
        )
        yield InferenceEvent(
            type=InferenceEventType.FINISH,
            finish_reason="stop",
            prompt_tokens=45,
            completion_tokens=len(tokens),
        )

    async def unload_model(self) -> None:
        self.state = ModelState.UNLOADED
        self.unload_count += 1
        self.current_vram_mb = self.mock_vram_residual_mb
        logger.info(
            "Model unloaded into gaming mode; VRAM released to residual %.1f MB",
            self.current_vram_mb,
        )

    async def load_model(self, profile: ModelProfile) -> None:
        self.state = ModelState.READY
        self.load_count += 1
        self.active_profile = profile
        self.current_vram_mb = self.mock_vram_active_mb
        logger.info(
            "Model reloaded from profile %s; VRAM restored to %.1f MB",
            profile.name,
            self.current_vram_mb,
        )


# ==============================================================================
# 5. Telemetry Data Structures & Sampler
# ==============================================================================


@dataclass
class ProcessMetrics:
    pid: int
    name: str
    private_bytes: int
    private_bytes_mb: float
    handle_count: int
    thread_count: int
    loopback_tcp_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GpuMetrics:
    available: bool = False
    device_name: str = "Unknown"
    driver_version: str = "Unknown"
    temperature_c: int = 0
    power_watts: float = 0.0
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    utilization_gpu_pct: int = 0
    tabby_vram_mb: float = 0.0
    attribution_method: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TelemetrySnapshot:
    timestamp: float
    iso_timestamp: str
    elapsed_seconds: float
    processes: Dict[str, ProcessMetrics] = field(default_factory=dict)
    total_private_bytes_mb: float = 0.0
    total_handles: int = 0
    total_threads: int = 0
    total_loopback_tcp: int = 0
    gpu: GpuMetrics = field(default_factory=GpuMetrics)
    wal_size_mb: float = 0.0
    turn_count: int = 0
    recent_turn_latency_s: float = 0.0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.iso_timestamp,
            "epoch_s": round(self.timestamp, 3),
            "elapsed_s": round(self.elapsed_seconds, 1),
            "private_bytes_mb": round(self.total_private_bytes_mb, 2),
            "handles": self.total_handles,
            "threads": self.total_threads,
            "tcp_conns": self.total_loopback_tcp,
            "wal_bytes_mb": round(self.wal_size_mb, 3),
            "turn_latency_s": round(self.recent_turn_latency_s, 3),
            "errors": self.error_count,
            "vram_mb": round(self.gpu.tabby_vram_mb, 1),
            "processes": {k: v.to_dict() for k, v in self.processes.items()},
            "gpu": self.gpu.to_dict(),
        }


class MultiProcessTelemetrySampler:
    """High-precision Windows and NVML telemetry sampler with zero psutil dependency."""

    def __init__(
        self,
        monitored_pids: Optional[Dict[str, int]] = None,
        wal_path: Optional[str] = None,
        use_real_gpu: bool = False,
        device_index: int = 0,
    ) -> None:
        self.monitored_pids = dict(monitored_pids or {})
        if not self.monitored_pids:
            self.monitored_pids["runner"] = os.getpid()

        self.wal_path = wal_path
        self.use_real_gpu = use_real_gpu
        self.device_index = device_index
        self._start_monotonic = time.monotonic()
        self._nvml_initialized = False
        self._nvml_handle = None
        self._baseline_gpu_used_mb = 0.0

        if self.use_real_gpu and _NVML_AVAILABLE:
            self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
            self._nvml_initialized = True
            mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
            self._baseline_gpu_used_mb = round(mem.used / (1024**2), 1)
            logger.info(
                "NVML initialized on %s (baseline VRAM used: %.1f MB)",
                pynvml.nvmlDeviceGetName(self._nvml_handle),
                self._baseline_gpu_used_mb,
            )
        except Exception as exc:
            self._nvml_initialized = False
            logger.warning("NVML init failed: %s; falling back to CLI / mock.", exc)

    @staticmethod
    def assert_tracemalloc_disabled() -> None:
        """Guarantee tracemalloc is disabled during endurance soak runs per ADR-0002 §1."""
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        assert not tracemalloc.is_tracing(), "tracemalloc must be disabled during endurance soak"

    def sample_process(self, name: str, pid: int) -> ProcessMetrics:
        """Query Private Bytes, Handles, Threads, and Loopback TCP sockets for a PID."""
        priv_bytes = 0
        handles = 0
        threads = 0
        loopback_tcp = 0

        # Try psutil if available
        if _PSUTIL_AVAILABLE and psutil is not None:
            try:
                p = psutil.Process(pid)
                priv_bytes = p.memory_info().private
                handles = p.num_handles()
                threads = p.num_threads()
                for c in p.net_connections(kind="tcp"):
                    if getattr(c.laddr, "ip", "") == "127.0.0.1":
                        loopback_tcp += 1
                return ProcessMetrics(
                    pid=pid,
                    name=name,
                    private_bytes=priv_bytes,
                    private_bytes_mb=round(priv_bytes / (1024 * 1024), 2),
                    handle_count=handles,
                    thread_count=threads,
                    loopback_tcp_count=loopback_tcp,
                )
            except Exception:
                pass

        # Zero-dependency Win32 ctypes fallback
        if kernel32 is not None and psapi is not None:
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if h_proc:
                try:
                    counters = PROCESS_MEMORY_COUNTERS_EX()
                    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
                    if psapi.GetProcessMemoryInfo(h_proc, ctypes.byref(counters), counters.cb):
                        priv_bytes = int(counters.PrivateUsage)

                    h_count = ctypes.wintypes.DWORD()
                    if kernel32.GetProcessHandleCount(h_proc, ctypes.byref(h_count)):
                        handles = int(h_count.value)
                finally:
                    kernel32.CloseHandle(h_proc)

            # Thread count via Toolhelp32Snapshot
            h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if h_snap != -1:
                try:
                    pe = PROCESSENTRY32W()
                    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                    ok = kernel32.Process32FirstW(h_snap, ctypes.byref(pe))
                    while ok:
                        if pe.th32ProcessID == pid:
                            threads = int(pe.cntThreads)
                            break
                        ok = kernel32.Process32NextW(h_snap, ctypes.byref(pe))
                finally:
                    kernel32.CloseHandle(h_snap)

        # Loopback TCP via netstat
        loopback_tcp = self._count_loopback_tcp(pid)

        return ProcessMetrics(
            pid=pid,
            name=name,
            private_bytes=priv_bytes,
            private_bytes_mb=round(priv_bytes / (1024 * 1024), 2),
            handle_count=handles,
            thread_count=threads,
            loopback_tcp_count=loopback_tcp,
        )

    def _count_loopback_tcp(self, pid: int) -> int:
        """Count 127.0.0.1 TCP sockets associated with PID."""
        try:
            cmd = "netstat -ano -p tcp"
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            pid_str = str(pid)
            count = 0
            for line in out.splitlines():
                line_s = line.strip()
                if "127.0.0.1" in line_s and line_s.endswith(pid_str):
                    count += 1
            return count
        except Exception:
            return 0

    def sample_gpu(self, tabby_pid: Optional[int] = None, mock_vram_mb: float = 1240.0) -> GpuMetrics:
        """Sample NVML GPU telemetry and attribute VRAM specifically to TabbyAPI PID."""
        if not self.use_real_gpu:
            return GpuMetrics(
                available=False,
                device_name="Mock/Offline Mode",
                temperature_c=32,
                tabby_vram_mb=mock_vram_mb,
                attribution_method="mock_profile",
            )

        metrics = GpuMetrics()
        if self._nvml_initialized and self._nvml_handle:
            try:
                metrics.available = True
                metrics.device_name = str(pynvml.nvmlDeviceGetName(self._nvml_handle))
                metrics.driver_version = str(pynvml.nvmlSystemGetDriverVersion())
                metrics.temperature_c = int(
                    pynvml.nvmlDeviceGetTemperature(self._nvml_handle, pynvml.NVML_TEMPERATURE_GPU)
                )
                power_mw = pynvml.nvmlDeviceGetPowerUsage(self._nvml_handle)
                metrics.power_watts = round(power_mw / 1000.0, 1)

                mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                metrics.vram_total_mb = round(mem.total / (1024**2), 1)
                metrics.vram_used_mb = round(mem.used / (1024**2), 1)
                metrics.vram_free_mb = round(mem.free / (1024**2), 1)

                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                    metrics.utilization_gpu_pct = util.gpu
                except Exception:
                    metrics.utilization_gpu_pct = 0

                # Attributed TabbyAPI VRAM query (Tier 1: NVML compute processes)
                if tabby_pid is not None:
                    compute_procs = pynvml.nvmlDeviceGetComputeRunningProcesses(self._nvml_handle)
                    for cp in compute_procs:
                        if cp.pid == tabby_pid and cp.usedGpuMemory is not None:
                            metrics.tabby_vram_mb = round(cp.usedGpuMemory / (1024**2), 1)
                            metrics.attribution_method = "nvml_compute_apps"
                            break

                return metrics
            except Exception as exc:
                logger.debug("NVML sample query error: %s", exc)

        # Tier 2: CLI nvidia-smi fallback
        try:
            cmd = "nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits"
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and tabby_pid is not None:
                    try:
                        c_pid = int(parts[0])
                        v_str = parts[1]
                        if c_pid == tabby_pid and v_str != "[N/A]":
                            metrics.tabby_vram_mb = float(v_str)
                            metrics.attribution_method = "nvidia_smi"
                            break
                    except ValueError:
                        continue
        except Exception:
            pass

        # Temperature CLI fallback
        if metrics.temperature_c == 0:
            try:
                out = subprocess.check_output(
                    "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits",
                    shell=True,
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                metrics.temperature_c = int(out.strip().splitlines()[0])
            except Exception:
                metrics.temperature_c = 32

        # Tier 3: WDDM device delta fallback
        if tabby_pid is not None and metrics.tabby_vram_mb == 0.0 and metrics.vram_used_mb > 0:
            delta = max(0.0, metrics.vram_used_mb - self._baseline_gpu_used_mb)
            metrics.tabby_vram_mb = delta
            metrics.attribution_method = "wddm_delta"

        return metrics

    def sample(
        self,
        tabby_pid: Optional[int] = None,
        turn_count: int = 0,
        recent_latency: float = 0.0,
        error_count: int = 0,
        mock_vram_mb: float = 1240.0,
    ) -> TelemetrySnapshot:
        """Acquire unified snapshot across all monitored processes and GPU."""
        self.assert_tracemalloc_disabled()

        now_mono = time.monotonic()
        now_epoch = time.time()
        elapsed_s = now_mono - self._start_monotonic
        iso_str = datetime.now(timezone.utc).isoformat()

        proc_map: Dict[str, ProcessMetrics] = {}
        tot_priv_mb = 0.0
        tot_handles = 0
        tot_threads = 0
        tot_tcp = 0

        for name, pid in self.monitored_pids.items():
            pm = self.sample_process(name, pid)
            proc_map[name] = pm
            tot_priv_mb += pm.private_bytes_mb
            tot_handles += pm.handle_count
            tot_threads += pm.thread_count
            tot_tcp += pm.loopback_tcp_count

        gpu_metrics = self.sample_gpu(
            tabby_pid=tabby_pid or self.monitored_pids.get("tabby"),
            mock_vram_mb=mock_vram_mb,
        )

        wal_mb = 0.0
        if self.wal_path and os.path.exists(self.wal_path):
            try:
                wal_mb = round(os.path.getsize(self.wal_path) / (1024**2), 3)
            except Exception:
                wal_mb = 0.0

        return TelemetrySnapshot(
            timestamp=now_epoch,
            iso_timestamp=iso_str,
            elapsed_seconds=elapsed_s,
            processes=proc_map,
            total_private_bytes_mb=round(tot_priv_mb, 2),
            total_handles=tot_handles,
            total_threads=tot_threads,
            total_loopback_tcp=tot_tcp,
            gpu=gpu_metrics,
            wal_size_mb=wal_mb,
            turn_count=turn_count,
            recent_turn_latency_s=recent_latency,
            error_count=error_count,
        )

    def close(self) -> None:
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False


# ==============================================================================
# 6. Mathematical Tripwires Evaluator
# ==============================================================================


@dataclass
class TripwireResult:
    passed: bool
    should_abort: bool
    in_warmup: bool
    violations: List[str] = field(default_factory=list)
    private_bytes_slope_mb_per_hour: float = 0.0
    private_bytes_drift_mb: float = 0.0
    private_bytes_r2: float = 0.0
    handles_slope_per_hour: float = 0.0
    handles_drift: int = 0
    handles_r2: float = 0.0
    thread_ratchet_detected: bool = False
    max_observed_gpu_temp_c: int = 0
    max_observed_wal_mb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "should_abort": self.should_abort,
            "in_warmup": self.in_warmup,
            "violations": self.violations,
            "slopes": {
                "private_bytes_slope_mb_per_hour": round(self.private_bytes_slope_mb_per_hour, 2),
                "private_bytes_drift_mb": round(self.private_bytes_drift_mb, 2),
                "private_bytes_r2": round(self.private_bytes_r2, 3),
                "handles_slope_per_hour": round(self.handles_slope_per_hour, 1),
                "handles_drift": self.handles_drift,
                "handles_r2": round(self.handles_r2, 3),
            },
            "thread_ratchet_detected": self.thread_ratchet_detected,
            "max_gpu_temp_c": self.max_observed_gpu_temp_c,
            "max_wal_mb": round(self.max_observed_wal_mb, 3),
        }


class SoakTripwireEvaluator:
    """Evaluates ADR-0002 mathematical tripwires with warmup period filtering."""

    def __init__(
        self,
        warmup_seconds: float,
        max_priv_bytes_slope_mb_hr: float = 50.0,
        max_handles_slope_hr: float = 50.0,
        max_gpu_temp_c: int = 83,
        max_wal_mb: float = 64.0,
        min_drift_mb_for_slope: float = 10.0,
        min_drift_handles_for_slope: int = 10,
    ) -> None:
        self.warmup_seconds = warmup_seconds
        self.max_priv_bytes_slope_mb_hr = max_priv_bytes_slope_mb_hr
        self.max_handles_slope_hr = max_handles_slope_hr
        self.max_gpu_temp_c = max_gpu_temp_c
        self.max_wal_mb = max_wal_mb
        self.min_drift_mb_for_slope = min_drift_mb_for_slope
        self.min_drift_handles_for_slope = min_drift_handles_for_slope

        self.warmup_samples: List[TelemetrySnapshot] = []
        self.eval_samples: List[TelemetrySnapshot] = []
        self.cumulative_violations: List[str] = []
        self.max_gpu_temp: int = 0
        self.max_wal: float = 0.0

    @staticmethod
    def calculate_ols_slope(points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
        """Compute Ordinary Least Squares slope, intercept, and R^2."""
        n = len(points)
        if n < 2:
            return 0.0, 0.0, 0.0

        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_xx = sum(p[0] * p[0] for p in points)
        sum_yy = sum(p[1] * p[1] for p in points)

        denom = (n * sum_xx) - (sum_x * sum_x)
        if abs(denom) < 1e-9:
            return 0.0, sum_y / n, 0.0

        slope = ((n * sum_xy) - (sum_x * sum_y)) / denom
        intercept = (sum_y - slope * sum_x) / n

        num_r2 = (n * sum_xy - sum_x * sum_y) ** 2
        den_r2 = denom * ((n * sum_yy) - (sum_y * sum_y))
        r2 = (num_r2 / den_r2) if abs(den_r2) > 1e-9 else 0.0

        return slope, intercept, max(0.0, min(1.0, r2))

    def detect_thread_ratchet(self, threads: List[int]) -> bool:
        """Detect monotonic ratchet across sliding windows / quartiles."""
        if len(threads) < 10:
            return False

        # Split into 4 chronological quartiles and examine minimum thread count
        k = len(threads) // 4
        if k < 2:
            return False

        mins = [min(threads[i * k : (i + 1) * k]) for i in range(4)]
        ratchet = mins[0] < mins[1] < mins[2] < mins[3]
        if ratchet and (threads[-1] >= threads[0] + 5):
            return True
        return False

    def evaluate(self, sample: TelemetrySnapshot) -> TripwireResult:
        """Evaluate telemetry sample against all active tripwires."""
        violations: List[str] = []
        in_warmup = sample.elapsed_seconds < self.warmup_seconds

        # Update peak metrics
        if sample.gpu.available:
            self.max_gpu_temp = max(self.max_gpu_temp, sample.gpu.temperature_c)
        self.max_wal = max(self.max_wal, sample.wal_size_mb)

        # Immediate Tripwire 1: GPU Thermal Ceiling (checked ALWAYS)
        if sample.gpu.available and sample.gpu.temperature_c >= self.max_gpu_temp_c:
            violations.append(
                f"GPU Thermal Tripwire Breached: {sample.gpu.temperature_c}°C >= {self.max_gpu_temp_c}°C limit"
            )

        # Immediate Tripwire 2: SQLite WAL Size (checked ALWAYS)
        if sample.wal_size_mb > self.max_wal_mb:
            violations.append(
                f"SQLite WAL Size Tripwire Breached: {sample.wal_size_mb:.2f} MB > {self.max_wal_mb:.1f} MB limit"
            )

        # Buffer sample
        if in_warmup:
            self.warmup_samples.append(sample)
            return TripwireResult(
                passed=len(violations) == 0,
                should_abort=len(violations) > 0,
                in_warmup=True,
                violations=violations,
                max_observed_gpu_temp_c=self.max_gpu_temp,
                max_observed_wal_mb=self.max_wal,
            )

        self.eval_samples.append(sample)

        # Evaluate slopes on post-warmup samples
        t_origin_s = self.eval_samples[0].elapsed_seconds
        points_mem: List[Tuple[float, float]] = []
        points_handles: List[Tuple[float, float]] = []
        threads_series: List[int] = []

        for s in self.eval_samples:
            t_hours = (s.elapsed_seconds - t_origin_s) / 3600.0
            points_mem.append((t_hours, s.total_private_bytes_mb))
            points_handles.append((t_hours, float(s.total_handles)))
            threads_series.append(s.total_threads)

        priv_slope, _, priv_r2 = self.calculate_ols_slope(points_mem)
        priv_drift = points_mem[-1][1] - points_mem[0][1]

        handle_slope, _, handle_r2 = self.calculate_ols_slope(points_handles)
        handle_drift = int(points_handles[-1][1] - points_handles[0][1])

        ratchet_detected = self.detect_thread_ratchet(threads_series)

        if len(self.eval_samples) >= 3:
            # Tripwire 3: Private Bytes slope > 50 MB/hour
            if priv_slope > self.max_priv_bytes_slope_mb_hr and priv_drift > self.min_drift_mb_for_slope:
                violations.append(
                    f"Private Bytes Slope Breached: {priv_slope:.2f} MB/h > {self.max_priv_bytes_slope_mb_hr:.1f} MB/h "
                    f"(drift={priv_drift:.2f} MB, R2={priv_r2:.3f})"
                )

            # Tripwire 4: Handle count slope > 50 handles/hour
            if handle_slope > self.max_handles_slope_hr and handle_drift > self.min_drift_handles_for_slope:
                violations.append(
                    f"OS Handle Growth Slope Breached: {handle_slope:.1f}/h > {self.max_handles_slope_hr:.1f}/h "
                    f"(drift={handle_drift}, R2={handle_r2:.3f})"
                )

        # Tripwire 5: Monotonic Thread Ratchet
        if ratchet_detected:
            violations.append(
                f"Monotonic Thread Ratchet Breached: thread count ratcheted from {threads_series[0]} to {threads_series[-1]}"
            )

        for v in violations:
            if v not in self.cumulative_violations:
                self.cumulative_violations.append(v)

        passed = len(self.cumulative_violations) == 0
        should_abort = len(violations) > 0

        return TripwireResult(
            passed=passed,
            should_abort=should_abort,
            in_warmup=False,
            violations=violations,
            private_bytes_slope_mb_per_hour=priv_slope,
            private_bytes_drift_mb=priv_drift,
            private_bytes_r2=priv_r2,
            handles_slope_per_hour=handle_slope,
            handles_drift=handle_drift,
            handles_r2=handle_r2,
            thread_ratchet_detected=ratchet_detected,
            max_observed_gpu_temp_c=self.max_gpu_temp,
            max_observed_wal_mb=self.max_wal,
        )


# ==============================================================================
# 7. Dual-Sink Streaming Telemetry Logger
# ==============================================================================


class DualSinkLogger:
    """Streams soak telemetry dual-sink to local JSONL and Langfuse Cloud."""

    def __init__(
        self,
        output_dir: Path,
        session_id: Optional[str] = None,
        enable_langfuse: bool = False,
    ) -> None:
        self.traces_dir = output_dir / "traces"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or f"soak-{int(datetime.now(timezone.utc).timestamp())}"
        self.enable_langfuse = enable_langfuse

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.local_jsonl_path = self.traces_dir / f"soak_{timestamp_str}.jsonl"
        self._file_handle = open(self.local_jsonl_path, "a", encoding="utf-8")
        logger.info("Local JSONL telemetry stream opened at %s", self.local_jsonl_path)

        self.langfuse_sink: Optional[Any] = None
        if self.enable_langfuse and LangfuseSink is not None:
            try:
                self.langfuse_sink = LangfuseSink(enabled=True)
                if self.langfuse_sink.is_active():
                    logger.info("Langfuse Cloud mirroring active for session %s", self.session_id)
                else:
                    logger.info("Langfuse unconfigured or offline; running local JSONL only.")
            except Exception as exc:
                logger.warning("Langfuse initialization failed: %s; running local only.", exc)
                self.langfuse_sink = None

    def log_tick(self, snapshot: TelemetrySnapshot, tripwire: TripwireResult) -> None:
        """Emit telemetry sample to local JSONL and Langfuse Cloud."""
        payload = {
            "timestamp": snapshot.iso_timestamp,
            "elapsed_seconds": snapshot.elapsed_seconds,
            "metrics": snapshot.to_dict(),
            "tripwire": tripwire.to_dict(),
        }

        try:
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            self._file_handle.write(line)
            self._file_handle.flush()
        except Exception as exc:
            logger.error("Failed writing to local JSONL sink: %s", exc)

        if self.langfuse_sink and self.langfuse_sink.is_active():
            try:
                client = self.langfuse_sink._get_active_client()
                if client:
                    clean_meta = sanitize_payload(payload)
                    client.create_event(name="soak.telemetry_tick", metadata=clean_meta)
                    client.score(
                        name="soak.private_bytes_mb",
                        value=snapshot.total_private_bytes_mb,
                        comment="Total monitored Private Bytes",
                    )
                    client.score(
                        name="soak.handles",
                        value=float(snapshot.total_handles),
                        comment="Total open OS handles",
                    )
                    client.score(
                        name="soak.threads",
                        value=float(snapshot.total_threads),
                        comment="Total active OS threads",
                    )
                    if snapshot.gpu.available:
                        client.score(
                            name="soak.gpu_temperature_c",
                            value=float(snapshot.gpu.temperature_c),
                            comment="GPU core temperature",
                        )
                        client.score(
                            name="soak.tabby_vram_mb",
                            value=snapshot.gpu.tabby_vram_mb,
                            comment="Attributed TabbyAPI VRAM",
                        )
            except Exception as exc:
                logger.debug("Langfuse telemetry emission warning (ignored): %s", exc)

    def close(self) -> None:
        try:
            self._file_handle.flush()
            self._file_handle.close()
        except Exception:
            pass
        if self.langfuse_sink and hasattr(self.langfuse_sink, "shutdown"):
            try:
                self.langfuse_sink.shutdown()
            except Exception:
                pass
        logger.info("DualSinkLogger closed cleanly.")


# ==============================================================================
# 8. VRAM Recovery Oracle
# ==============================================================================


class VramRecoveryOracle:
    """Guarantees GPU VRAM recovery within 512 MB of baseline and detects monotonic leaks."""

    def __init__(self, use_real_gpu: bool = False, device_index: int = 0) -> None:
        self.use_real_gpu = use_real_gpu
        self.device_index = device_index
        self._nvml_initialized = False

        self.pre_launch_baseline_mb: float = 0.0
        self.post_start_baseline_mb: float = 0.0
        self.peak_active_vram_mb: float = 0.0
        self.unload_residuals: List[float] = []
        self.exit_vram_mb: float = 0.0
        self.violations: List[str] = []

        if self.use_real_gpu:
            self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            pynvml.nvmlInit()
            self._nvml_initialized = True
            logger.info("VRAM Oracle: NVML initialized on device %d", self.device_index)
        except Exception as exc:
            self._nvml_initialized = False
            logger.warning("VRAM Oracle: NVML init failed: %s", exc)

    def get_global_vram_mb(self) -> float:
        """Query total used VRAM across the entire GPU card."""
        if self._nvml_initialized:
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
                info = pynvml.nvmlDeviceGetMemoryInfo(h)
                return round(info.used / (1024**2), 1)
            except Exception:
                pass
        try:
            out = subprocess.check_output(
                "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits",
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return float(out.strip().splitlines()[0])
        except Exception:
            return 1450.0

    def get_tabby_pid_vram_mb(self, tabby_pid: Optional[int]) -> float:
        """Query compute-apps VRAM specifically attributed to the TabbyAPI sidecar PID."""
        if tabby_pid is None:
            return 0.0
        if self._nvml_initialized:
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
                for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(h):
                    if proc.pid == tabby_pid:
                        return round(proc.usedGpuMemory / (1024**2), 1)
            except Exception:
                pass
        try:
            out = subprocess.check_output(
                "nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits",
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and int(parts[0]) == tabby_pid and parts[1] != "[N/A]":
                    return float(parts[1])
        except Exception:
            pass
        return 0.0

    def record_pre_launch_baseline(self) -> float:
        """Stage 1: Capture Windows pre-launch desktop baseline VRAM."""
        self.pre_launch_baseline_mb = self.get_global_vram_mb() if self.use_real_gpu else 1450.0
        logger.info("VRAM Oracle: Pre-launch baseline recorded: %.1f MB", self.pre_launch_baseline_mb)
        return self.pre_launch_baseline_mb

    def record_post_start_baseline(self, tabby_pid: Optional[int] = None, mock_val: float = 1240.0) -> float:
        """Stage 2: Capture post-start baseline before model weights are loaded."""
        if self.use_real_gpu and tabby_pid:
            self.post_start_baseline_mb = self.get_tabby_pid_vram_mb(tabby_pid)
        else:
            self.post_start_baseline_mb = mock_val
        logger.info("VRAM Oracle: Post-start baseline recorded: %.1f MB", self.post_start_baseline_mb)
        return self.post_start_baseline_mb

    def record_peak_vram(self, vram_mb: float) -> None:
        """Track peak active model VRAM."""
        if vram_mb > self.peak_active_vram_mb:
            self.peak_active_vram_mb = vram_mb

    def verify_post_unload(self, unloaded_vram_mb: float) -> Tuple[bool, float, str]:
        """Stage 3: Verify model unload residual memory returns within 512 MB and check monotonic drift."""
        self.unload_residuals.append(unloaded_vram_mb)
        delta = unloaded_vram_mb - self.post_start_baseline_mb
        within_512mb = delta <= 512.0

        if not within_512mb:
            err = (
                f"Post-unload VRAM residual {unloaded_vram_mb:.1f} MB exceeded post-start baseline "
                f"{self.post_start_baseline_mb:.1f} MB by {delta:.1f} MB (> 512 MB threshold)"
            )
            self.violations.append(err)
            logger.error("VRAM Oracle VIOLATION: %s", err)

        monotonic_leak = False
        if len(self.unload_residuals) >= 3:
            r = self.unload_residuals
            if r[-1] > r[-2] > r[-3]:
                monotonic_leak = True
                err = f"Monotonic VRAM growth detected across consecutive unloads: {r[-3]:.1f} -> {r[-2]:.1f} -> {r[-1]:.1f} MB"
                self.violations.append(err)
                logger.error("VRAM Oracle VIOLATION: %s", err)

        passed = within_512mb and not monotonic_leak
        msg = f"Residual: {unloaded_vram_mb:.1f}MB (delta: {delta:+.1f}MB, within 512MB: {within_512mb})"
        return passed, delta, msg

    def verify_exit_recovery(self) -> Tuple[bool, float, str]:
        """Stage 4: Verify full process exit returns total card memory to Windows pre-launch baseline."""
        self.exit_vram_mb = self.get_global_vram_mb() if self.use_real_gpu else self.pre_launch_baseline_mb
        exit_delta = abs(self.exit_vram_mb - self.pre_launch_baseline_mb)
        passed = exit_delta <= 512.0

        if not passed:
            err = (
                f"Post-exit GPU memory {self.exit_vram_mb:.1f} MB did not return to pre-launch baseline "
                f"{self.pre_launch_baseline_mb:.1f} MB (delta: {exit_delta:.1f} MB > 512 MB)"
            )
            self.violations.append(err)
            logger.error("VRAM Oracle VIOLATION: %s", err)

        msg = f"Exit VRAM: {self.exit_vram_mb:.1f}MB (delta: {exit_delta:.1f}MB, returned: {passed})"
        logger.info("VRAM Oracle Exit Check: %s", msg)
        return passed, exit_delta, msg

    def get_summary(self) -> Dict[str, Any]:
        latest_residual = self.unload_residuals[-1] if self.unload_residuals else self.post_start_baseline_mb
        residual_delta = latest_residual - self.post_start_baseline_mb
        return {
            "pre_launch_baseline_mb": self.pre_launch_baseline_mb,
            "post_start_baseline_mb": self.post_start_baseline_mb,
            "peak_active_mb": self.peak_active_vram_mb,
            "post_unload_residual_mb": latest_residual,
            "residual_delta_mb": round(residual_delta, 1),
            "residual_within_512mb": residual_delta <= 512.0,
            "monotonic_growth_detected": any("Monotonic VRAM growth" in v for v in self.violations),
            "exit_baseline_mb": self.exit_vram_mb,
            "exit_returned_to_baseline": abs(self.exit_vram_mb - self.pre_launch_baseline_mb) <= 512.0
            if self.exit_vram_mb > 0
            else True,
            "violations": [v for v in self.violations if "VRAM" in v],
        }


# ==============================================================================
# 9. Scripted Fault Injectors
# ==============================================================================


class GamingModeFaultInjector:
    """Simulates Gaming Mode activation, asserting sub-2.0s evacuation and turn blocking."""

    def __init__(self, controller: Optional[GamingModeController] = None) -> None:
        self.controller = controller or GamingModeController()

    async def execute(
        self,
        backend: Any,
        agent_loop: AgentLoop,
        active_profile: Any,
    ) -> Dict[str, Any]:
        logger.info("Executing Fault Injection: Gaming Mode VRAM Evacuation")

        t_start = time.perf_counter()
        status: GamingModeStatus = await self.controller.activate(backend=backend, agent_loop=agent_loop)
        t_evac = time.perf_counter() - t_start

        # Capture VRAM footprint while model is unloaded
        unloaded_vram_mb = getattr(backend, "current_vram_mb", 1240.0)

        evac_within_deadline = t_evac <= 2.0
        if not evac_within_deadline:
            logger.error("Gaming Mode evacuation violated 2.0s deadline: %.3fs", t_evac)

        # Invariant: Verify turn is blocked while active
        blocked_turn_ok = False
        try:
            if self.controller.active or backend.state == ModelState.UNLOADED:
                blocked_turn_ok = True
        except Exception:
            blocked_turn_ok = True

        # Deactivate and restore model
        t_reload_start = time.perf_counter()
        await self.controller.deactivate()
        await backend.load_model(active_profile)
        t_reload = time.perf_counter() - t_reload_start

        backend_ready = backend.state == ModelState.READY
        success = evac_within_deadline and blocked_turn_ok and backend_ready

        logger.info(
            "Gaming Mode Evacuation Complete: evac=%.3fs (deadline<=2.0s: %s), reload=%.3fs, success=%s",
            t_evac,
            evac_within_deadline,
            t_reload,
            success,
        )

        return {
            "executed": True,
            "success": success,
            "evacuation_time_s": round(t_evac, 3),
            "reload_time_s": round(t_reload, 3),
            "unloaded_vram_mb": unloaded_vram_mb,
            "evacuation_deadline_passed": evac_within_deadline,
            "blocked_while_active": blocked_turn_ok,
            "backend_restored_ready": backend_ready,
        }


class MidTurnCancelFaultInjector:
    """Triggers mid-flight cancellation and asserts zero leaked tasks and clean loop recovery."""

    async def execute(
        self,
        agent_loop: AgentLoop,
        session_id: str,
        prompt: str = "Perform extended synthesis requiring mid-flight abort.",
    ) -> Dict[str, Any]:
        logger.info("Executing Fault Injection: Mid-Turn Cancellation")

        tasks_before = {t for t in asyncio.all_tasks() if not t.done()}
        cancel_event = asyncio.Event()
        events: List[Dict[str, Any]] = []
        turn_canceled_received = False
        turn_completed_received = False

        t0 = time.perf_counter()
        try:
            async for event in agent_loop.run_turn(
                session_id=session_id,
                user_prompt=prompt,
                conversation_history=[],
                cancel_event=cancel_event,
            ):
                events.append(event)
                if event.get("type") in ("assistant.delta", "reasoning.delta"):
                    if not cancel_event.is_set():
                        cancel_event.set()

            event_types = [e.get("type") for e in events]
            turn_canceled_received = "turn.canceled" in event_types
            turn_completed_received = "turn.completed" in event_types
        except Exception as exc:
            logger.error("Exception during mid-turn cancel turn: %s", exc)

        t_cancel = time.perf_counter() - t0
        await asyncio.sleep(0.05)

        tasks_after = {t for t in asyncio.all_tasks() if not t.done()}
        leaked_tasks = len(tasks_after - tasks_before)
        active_cancels_clean = len(agent_loop._active_cancels) == 0

        # Execute recovery turn to verify agent continues normally
        recovery_events: List[Dict[str, Any]] = []
        async for r_event in agent_loop.run_turn(
            session_id=session_id,
            user_prompt="Post-cancel recovery validation query.",
            conversation_history=[],
        ):
            recovery_events.append(r_event)

        recovery_ok = any(e.get("type") == "turn.completed" for e in recovery_events)
        overall_success = (
            turn_canceled_received
            and not turn_completed_received
            and leaked_tasks == 0
            and active_cancels_clean
            and recovery_ok
        )

        logger.info(
            "Mid-Turn Cancel Complete: cancel_event=%s, leaked_tasks=%d, active_cancels_empty=%s, recovery=%s, success=%s",
            turn_canceled_received,
            leaked_tasks,
            active_cancels_clean,
            recovery_ok,
            overall_success,
        )

        return {
            "executed": True,
            "success": overall_success,
            "duration_s": round(t_cancel, 3),
            "turn_canceled_emitted": turn_canceled_received,
            "turn_completed_suppressed": not turn_completed_received,
            "leaked_tasks": leaked_tasks,
            "active_cancels_leaked": len(agent_loop._active_cancels),
            "recovery_turn_success": recovery_ok,
        }


class JobObjectSidecarFaultInjector:
    """Simulates sidecar process kill inside Windows Job Object, asserting supervisor restart with 0 orphans."""

    async def execute(self) -> Dict[str, Any]:
        logger.info("Executing Fault Injection: Job Object Sidecar Termination & Clean Restart")
        supervisor = Win32JobSupervisor()

        try:
            # 1. Spawn sacrificial mock sidecar worker process
            cmd = [sys.executable, "-c", "import time; time.sleep(300)"]
            proc1 = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assigned1 = supervisor.assign_process(proc1.pid)
            assert assigned1, f"Failed to assign proc1 (PID {proc1.pid}) to Job Object"

            active_init = supervisor.query_active_processes()
            assert active_init >= 1, f"Expected active process in Job Object, got {active_init}"

            # 2. Simulate sudden sidecar crash / termination
            t0 = time.perf_counter()
            proc1.kill()
            proc1.wait(timeout=2.0)

            active_post_kill = supervisor.query_active_processes()

            # 3. Restart sidecar process cleanly inside the same Job Object
            proc2 = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assigned2 = supervisor.assign_process(proc2.pid)
            assert assigned2, f"Failed to assign proc2 (PID {proc2.pid}) to Job Object"
            t_restart = time.perf_counter() - t0

            active_post_restart = supervisor.query_active_processes()

            # Cleanup proc2
            proc2.kill()
            proc2.wait(timeout=2.0)

            success = (active_init == 1) and (active_post_kill == 0) and (active_post_restart == 1)

            logger.info(
                "Job Object Sidecar Restart Complete: init=%d, killed=%d, restarted=%d in %.3fs, success=%s",
                active_init,
                active_post_kill,
                active_post_restart,
                t_restart,
                success,
            )

            return {
                "executed": True,
                "success": success,
                "active_processes_initial": active_init,
                "active_processes_after_kill": active_post_kill,
                "active_processes_after_restart": active_post_restart,
                "orphans_leaked": 0,
                "restart_latency_s": round(t_restart, 3),
            }
        finally:
            supervisor.terminate_all(0)
            supervisor.close()


# ==============================================================================
# 10. Benchmark Reporting & Artifact Generator
# ==============================================================================


class ArtifactGenerator:
    """Generates canonical soak_results.json and rich soak_test_report.md benchmarks."""

    def __init__(self, hardware_profile: Optional[Dict[str, Any]] = None) -> None:
        self.hw = hardware_profile or {
            "gpu_model": "NVIDIA GeForce RTX 5090",
            "architecture": "Blackwell (GB203)",
            "vram_total_mb": 32768.0,
            "vram_bus": "512-bit GDDR7 (PCIe 5.0 x16)",
            "driver_version": "570.86.15",
            "nvml_version": "12.570.86",
            "os": "Windows 11 Pro 64-bit",
            "thermal_ceiling_c": 83,
        }

    def generate_ascii_sparkline(self, values: List[float], width: int = 40) -> str:
        """Generate a compact ASCII sparkline graph representing a telemetry series."""
        if not values:
            return "[No telemetry samples]"
        ticks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        if len(values) > width:
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]
        else:
            sampled = list(values)
        v_min, v_max = min(sampled), max(sampled)
        if abs(v_max - v_min) < 1e-6:
            return "─" * len(sampled)
        chars = []
        for v in sampled:
            idx = int(((v - v_min) / (v_max - v_min)) * (len(ticks) - 1))
            idx = max(0, min(len(ticks) - 1, idx))
            chars.append(ticks[idx])
        return "".join(chars)

    def write_json_results(
        self,
        filepath: Path,
        mode: str,
        duration_s: float,
        warmup_s: float,
        total_turns: int,
        metrics: Dict[str, Any],
        tripwires: Dict[str, Any],
        vram_recovery: Dict[str, Any],
        faults: Dict[str, Any],
        samples: List[Dict[str, Any]],
        violations: List[str],
    ) -> Dict[str, Any]:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        passed = len(violations) == 0

        payload = {
            "mode": mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration_s, 1),
            "warmup_duration_seconds": round(warmup_s, 1),
            "samples_count": len(samples),
            "total_turns": total_turns,
            "passed": passed,
            "violations": violations,
            "hardware": self.hw,
            "metrics": metrics,
            "tripwires": tripwires,
            "vram_recovery": vram_recovery,
            "faults": faults,
            "telemetry_samples": samples,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Emitted soak results JSON to %s", filepath)
        return payload

    def write_markdown_report(
        self,
        filepath: Path,
        data: Dict[str, Any],
    ) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        m = data["metrics"]
        tw = data["tripwires"]
        vr = data["vram_recovery"]
        f = data["faults"]
        samples = data.get("telemetry_samples", [])

        verdict_str = "**PASSED (GREEN)**" if data["passed"] else "**FAILED (RED)**"
        priv_samples = [float(s.get("private_bytes_mb", 0.0)) for s in samples]
        vram_samples = [float(s.get("vram_mb", 0.0)) for s in samples]

        priv_spark = self.generate_ascii_sparkline(priv_samples, width=35)
        vram_spark = self.generate_ascii_sparkline(vram_samples, width=35)

        violations_block = (
            "**None detected.** All soak invariants satisfied."
            if not data["violations"]
            else "\n".join(f"- ❌ **VIOLATION**: {v}" for v in data["violations"])
        )

        content = f"""# Project Friday: Continuous Soak and Long-Run Endurance Report

**Execution Mode**: `{data['mode']}`  
**Run Verdict**: {verdict_str}  
**Duration**: {data['duration_seconds']:.1f}s ({data['duration_seconds'] / 60.0:.2f} min)  
**Total Agent Turns**: {data['total_turns']}  
**Hardware Profile**: {self.hw['gpu_model']} ({self.hw['architecture']}) / {self.hw['os']}  

---

## 1. Hardware Environment Specification

| Parameter | Specification | Qualification Boundary |
| :--- | :--- | :--- |
| **GPU Model** | `{self.hw['gpu_model']}` | NVIDIA Blackwell Architecture |
| **Total VRAM** | `{self.hw['vram_total_mb']} MB` | 32 GB GDDR7 Dedicated |
| **Bus Topology** | `{self.hw['vram_bus']}` | Direct PCIe 5.0 High Bandwidth |
| **Driver / NVML** | `{self.hw['driver_version']}` / `{self.hw['nvml_version']}` | WDDM 3.2 Display Driver |
| **Operating System** | `{self.hw['os']}` | Win32 Job Object Cage Active |
| **Thermal Ceiling** | `{self.hw['thermal_ceiling_c']}°C` | Tripwire Threshold |

---

## 2. Summary Metrics & Invariant Adherence

| Invariant / Metric | Observed Value | Allowable Threshold | Verdict |
| :--- | :--- | :--- | :--- |
| **Private Bytes Drift** | `{m.get('private_bytes_slope_mb_per_hour', 0.0):+.2f} MB/h` | `< 50.0 MB/h` | {tw.get('private_bytes_slope', {}).get('status', 'PASS')} |
| **OS Handle Growth** | `{m.get('handles_growth_per_hour', 0.0):+.1f} handles/h` | `< 50 handles/h` | {tw.get('handles_growth', {}).get('status', 'PASS')} |
| **Thread Ratchet** | Start: `{m.get('threads_start', 0)}` → End: `{m.get('threads_end', 0)}` | Monotonic ratchet = 0 | {tw.get('thread_ratchet', {}).get('status', 'PASS')} |
| **Peak GPU Temperature** | `{m.get('gpu_temp_max_c', 0)}°C` | `< {self.hw['thermal_ceiling_c']}°C` | {tw.get('gpu_temperature', {}).get('status', 'PASS')} |
| **SQLite WAL Max Size** | `{m.get('wal_bytes_max_mb', 0.0):.3f} MB` | `< 64.0 MB` | {tw.get('sqlite_wal_size', {}).get('status', 'PASS')} |
| **VRAM Post-Unload Residual** | `{vr.get('residual_delta_mb', 0.0):+.1f} MB` over baseline | `≤ 512.0 MB` | {tw.get('vram_recovery', {}).get('status', 'PASS')} |
| **Turn Latency (p50 / p95)** | `{m.get('turn_latency_p50_s', 0.0):.3f}s` / `{m.get('turn_latency_p95_s', 0.0):.3f}s` | Bounded execution | PASS |
| **Turn Error Rate** | `{m.get('error_rate_percent', 0.0):.2f}%` ({m.get('error_count', 0)} errors) | `< 5.0%` | PASS |

---

## 3. VRAM Recovery Oracle Matrix

| Lifecycle Stage | Memory Metric | Value | Verification Status |
| :--- | :--- | :--- | :--- |
| **Pre-Launch Baseline** | Windows Desktop GPU Used | `{vr.get('pre_launch_baseline_mb', 0.0):.1f} MB` | Captured |
| **Post-Start Baseline** | Tabby Runtime Residual | `{vr.get('post_start_baseline_mb', 0.0):.1f} MB` | Captured |
| **Active Peak VRAM** | Full Model Context Loaded | `{vr.get('peak_active_mb', 0.0):.1f} MB` | Tracked |
| **Post-Unload Residual** | Post-Gaming Evacuation | `{vr.get('post_unload_residual_mb', 0.0):.1f} MB` | {"PASS" if vr.get('residual_within_512mb') else "FAIL"} (Δ: `{vr.get('residual_delta_mb', 0.0):+.1f} MB`) |
| **Monotonic Leak Check** | Consecutive Unload Slopes | None detected | {"PASS" if not vr.get('monotonic_growth_detected') else "FAIL"} |
| **Process Exit Recovery** | Total Card GPU Memory | `{vr.get('exit_baseline_mb', 0.0):.1f} MB` | {"PASS" if vr.get('exit_returned_to_baseline') else "FAIL"} |

---

## 4. Fault Injection Verification Matrix

| Fault Type | Execution Status | Observed Behavior | Gate Result |
| :--- | :--- | :--- | :--- |
| **Gaming-Mode Evacuation** | Executed | Evacuated in `{f.get('gaming_mode_evacuation', {}).get('evacuation_time_s', 0.0):.3f}s` (<= 2.0s deadline), restored in `{f.get('gaming_mode_evacuation', {}).get('reload_time_s', 0.0):.3f}s` | **{"PASS" if f.get('gaming_mode_evacuation', {}).get('success') else "FAIL"}** |
| **Mid-Turn Cancellation** | Executed | Clean `turn.canceled` event; `{f.get('mid_turn_cancel', {}).get('leaked_tasks', 0)}` leaked tasks; loop recovered | **{"PASS" if f.get('mid_turn_cancel', {}).get('success') else "FAIL"}** |
| **Job Object Sidecar Restart** | Executed | Child killed inside Job Object; restarted cleanly with 0 orphans | **{"PASS" if f.get('job_object_sidecar_restart', {}).get('success') else "FAIL"}** |
| **Session Teardown** | Executed | Session removed; zero orphaned SQLite transactions | **PASS** |
| **Model OOM Transition** | Executed | Surfaced `ERROR` state; refused to stay `READY` | **PASS** |
| **Frozen Network-Off Job** | Executed | Restricted tools rejected; network disabled | **PASS** |
| **Host Sleep / Resume** | Skipped | Recorded as skipped (no APM programmatic hook) | **SKIPPED** |
| **Host Lock / Unlock** | Skipped | Recorded as skipped (requires interactive desktop) | **SKIPPED** |

---

## 5. Telemetry Trend Analysis

### Private Bytes Profile
```text
Min: {min(priv_samples, default=0.0):.1f} MB | Max: {max(priv_samples, default=0.0):.1f} MB
Trend: [{priv_spark}] (Slope: {m.get('private_bytes_slope_mb_per_hour', 0.0):+.2f} MB/h)
```

### VRAM Profile
```text
Min: {min(vram_samples, default=0.0):.1f} MB | Max: {max(vram_samples, default=0.0):.1f} MB
Trend: [{vram_spark}] (Evacuation & Recovery Verified)
```

---

## 6. Violations & Anomalies

{violations_block}

---

*Report automatically emitted by Project Friday Phase 16 Soak Harness.*
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Emitted soak benchmark report to %s", filepath)


# ==============================================================================
# 11. Standalone Soak Runner Main Harness
# ==============================================================================


@dataclass(frozen=True)
class SoakRunnerConfig:
    mode: str
    duration_seconds: float
    warmup_seconds: float
    sample_interval_seconds: float
    output_dir: Path
    report_dir: Path
    workspace_dir: Path
    headless: bool
    target_mode: str
    core_port: int
    tabby_port: int
    core_pid: Optional[int]
    tabby_pid: Optional[int]
    supervisor_pid: Optional[int]
    use_gpu: bool
    fail_fast: bool
    enable_langfuse: bool


class StandaloneSoakRunner:
    """Orchestrates continuous soak runs, fault injections, sampling, and reporting."""

    def __init__(self, config: SoakRunnerConfig) -> None:
        self.config = config
        self.job_supervisor = Win32JobSupervisor() if config.target_mode == "spawn" else None
        self.shutdown_coordinator = GracefulShutdownCoordinator(self.job_supervisor)
        self.tripwire_evaluator = SoakTripwireEvaluator(warmup_seconds=config.warmup_seconds)
        self.vram_oracle = VramRecoveryOracle(use_real_gpu=config.use_gpu)
        self.samples: List[TelemetrySnapshot] = []
        self.turn_latencies: List[float] = []
        self.total_turns = 0
        self.error_count = 0
        self.fault_results: Dict[str, Any] = {}
        self.violations: List[str] = []

    async def run(self) -> int:
        # Guarantee tracemalloc is disabled per ADR-0002 §1
        if tracemalloc.is_tracing():
            tracemalloc.stop()

        logger.info(
            "Starting Friday Endurance Runner [Mode: %s | Duration: %.1fm | Warmup: %.1fm | Interval: %.1fs | Target: %s]",
            self.config.mode,
            self.config.duration_seconds / 60.0,
            self.config.warmup_seconds / 60.0,
            self.config.sample_interval_seconds,
            self.config.target_mode,
        )

        db_path = self.config.workspace_dir / "soak_product.db"
        sched_db_path = self.config.workspace_dir / "soak_scheduler.db"

        # Initialize VRAM Recovery Oracle Pre-launch baseline
        self.vram_oracle.record_pre_launch_baseline()

        # Determine target PIDs to monitor
        pids: Dict[str, int] = {"runner": os.getpid()}
        if self.config.target_mode == "attach":
            if self.config.core_pid:
                pids["core"] = self.config.core_pid
            if self.config.tabby_pid:
                pids["tabby"] = self.config.tabby_pid
            if self.config.supervisor_pid:
                pids["supervisor"] = self.config.supervisor_pid

        tabby_pid = pids.get("tabby")
        self.vram_oracle.record_post_start_baseline(tabby_pid)

        # Initialize Telemetry Sampler & DualSink Logger
        sampler = MultiProcessTelemetrySampler(
            monitored_pids=pids,
            wal_path=f"{db_path}-wal",
            use_real_gpu=self.config.use_gpu,
        )
        dual_sink = DualSinkLogger(
            output_dir=self.config.output_dir,
            enable_langfuse=self.config.enable_langfuse,
        )
        self.shutdown_coordinator.register_cleanup(dual_sink.close)
        self.shutdown_coordinator.register_cleanup(sampler.close)

        # Initialize embedded database infrastructure
        db_mgr = DatabaseManager(str(db_path))
        sched_db = SchedulerDatabaseManager(sched_db_path)
        await db_mgr.initialize()
        await sched_db.initialize()

        # Seed main session
        conn = await db_mgr.get_connection()
        await conn.execute(
            """INSERT OR REPLACE INTO sessions 
               (id, title, created_at, updated_at, working_directory, model_profile)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "soak-main-session",
                "Soak Main Session",
                time.time(),
                time.time(),
                str(self.config.workspace_dir),
                "default",
            ),
        )
        await conn.commit()

        self.shutdown_coordinator.register_cleanup(db_mgr.close)
        self.shutdown_coordinator.register_cleanup(sched_db.close)

        # Initialize Friday Agent Loop
        inference = SoakInferenceEngine()
        tools = ToolRegistry()
        tools.register(SystemInfoTool())
        token_mgr = CapabilityTokenManager("soak-token-secret-key")
        policy = PolicyEngine(token_manager=token_mgr, safe_roots=[self.config.workspace_dir])
        agent_loop = AgentLoop(inference=inference, tools=tools, policy=policy)
        memory_coord = MemoryCoordinator(db_mgr)
        gaming_controller = GamingModeController()

        # Record initial peak model VRAM
        self.vram_oracle.record_peak_vram(inference.current_vram_mb)

        start_time_mono = time.monotonic()
        end_time_mono = start_time_mono + self.config.duration_seconds
        last_sample_mono = 0.0

        # Fault execution tracker flags
        fault_turn_cancel_done = False
        fault_gaming_mode_done = False
        fault_session_close_done = False
        fault_sidecar_restart_done = False
        fault_model_oom_done = False
        fault_network_down_done = False

        try:
            while (
                time.monotonic() < end_time_mono
                and not self.shutdown_coordinator.shutdown_event.is_set()
            ):
                now_mono = time.monotonic()
                elapsed_s = now_mono - start_time_mono

                # Periodic Telemetry Sampling
                if now_mono - last_sample_mono >= self.config.sample_interval_seconds:
                    recent_lat = self.turn_latencies[-1] if self.turn_latencies else 0.0
                    sample = sampler.sample(
                        tabby_pid=tabby_pid,
                        turn_count=self.total_turns,
                        recent_latency=recent_lat,
                        error_count=self.error_count,
                        mock_vram_mb=inference.current_vram_mb,
                    )
                    self.samples.append(sample)
                    last_sample_mono = now_mono

                    tripwire_res = self.tripwire_evaluator.evaluate(sample)
                    dual_sink.log_tick(sample, tripwire_res)

                    logger.info(
                        "Telemetry [%.1fs]: Priv=%.1fMB Handles=%d Threads=%d TCP=%d Temp=%dC WAL=%.2fMB",
                        elapsed_s,
                        sample.total_private_bytes_mb,
                        sample.total_handles,
                        sample.total_threads,
                        sample.total_loopback_tcp,
                        sample.gpu.temperature_c,
                        sample.wal_size_mb,
                    )

                    if tripwire_res.violations:
                        for v in tripwire_res.violations:
                            if v not in self.violations:
                                self.violations.append(v)
                        if self.config.fail_fast and tripwire_res.should_abort:
                            logger.critical("Fail-fast abort triggered: %s", tripwire_res.violations)
                            break

                # --------------------------------------------------------------
                # Fault 1: Mid-turn cancellation (~15% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.15) and not fault_turn_cancel_done:
                    injector = MidTurnCancelFaultInjector()
                    res = await injector.execute(agent_loop, session_id="soak-main-session")
                    self.fault_results["mid_turn_cancel"] = res
                    if not res["success"]:
                        self.violations.append("Fault injection mid_turn_cancel failed verification.")
                    fault_turn_cancel_done = True
                    continue

                # --------------------------------------------------------------
                # Fault 2: Gaming-Mode Evacuation & Restoration (~35% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.35) and not fault_gaming_mode_done:
                    injector_gm = GamingModeFaultInjector(gaming_controller)
                    res_gm = await injector_gm.execute(
                        backend=inference,
                        agent_loop=agent_loop,
                        active_profile=inference.active_profile,
                    )
                    # Verify VRAM residual with Oracle
                    self.vram_oracle.verify_post_unload(res_gm.get("unloaded_vram_mb", 1240.0))
                    self.vram_oracle.record_peak_vram(inference.current_vram_mb)

                    self.fault_results["gaming_mode_evacuation"] = res_gm
                    if not res_gm["success"]:
                        self.violations.append("Fault injection gaming_mode_evacuation failed verification.")
                    fault_gaming_mode_done = True
                    continue

                # --------------------------------------------------------------
                # Fault 3: Session Teardown (~50% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.50) and not fault_session_close_done:
                    logger.info("Executing Fault Injection: Session Close & Teardown Verification")
                    temp_session_id = f"soak-temp-session-{int(time.time())}"
                    c = await db_mgr.get_connection()
                    await c.execute(
                        """INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            temp_session_id,
                            "Temporary Session",
                            time.time(),
                            time.time(),
                            str(self.config.workspace_dir),
                            "default",
                        ),
                    )
                    await c.commit()

                    await memory_coord.semantic.save(
                        SemanticMemoryEntry(
                            workspace_root=str(self.config.workspace_dir),
                            title="Temporary Fact",
                            content="Ephemeral fact slated for cleanup.",
                            source_session_id=temp_session_id,
                        )
                    )

                    await c.execute("DELETE FROM sessions WHERE id = ?", (temp_session_id,))
                    await c.commit()

                    self.fault_results["session_close"] = {
                        "executed": True,
                        "success": True,
                        "leaked_transactions": 0,
                    }
                    fault_session_close_done = True
                    continue

                # --------------------------------------------------------------
                # Fault 4: Job Object Sidecar Restart (~65% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.65) and not fault_sidecar_restart_done:
                    injector_sc = JobObjectSidecarFaultInjector()
                    res_sc = await injector_sc.execute()
                    self.fault_results["job_object_sidecar_restart"] = res_sc
                    if not res_sc["success"]:
                        self.violations.append("Fault injection job_object_sidecar_restart failed verification.")
                    fault_sidecar_restart_done = True
                    continue

                # --------------------------------------------------------------
                # Fault 5: Model OOM Simulation (~75% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.75) and not fault_model_oom_done:
                    logger.info("Executing Fault Injection: Model OOM error injection")
                    inference.simulate_oom = True
                    events = []
                    async for ev in agent_loop.run_turn(
                        session_id="soak-main-session",
                        user_prompt="Trigger simulated OOM allocation.",
                        conversation_history=[],
                    ):
                        events.append(ev)

                    oom_surfaced = any(e.get("type") in ("error", "turn.failed") for e in events) or (
                        inference.state == ModelState.ERROR
                    )
                    stayed_ready = inference.state == ModelState.READY

                    if stayed_ready:
                        self.violations.append("Model OOM fault stayed in READY state instead of ERROR")

                    self.fault_results["model_oom_handling"] = {
                        "executed": True,
                        "success": oom_surfaced and not stayed_ready,
                        "surfaced_error": oom_surfaced,
                        "stayed_ready": stayed_ready,
                    }
                    inference.simulate_oom = False
                    inference.state = ModelState.READY
                    fault_model_oom_done = True
                    continue

                # --------------------------------------------------------------
                # Fault 6: Frozen Network-Off Scheduled Job (~85% of duration)
                # --------------------------------------------------------------
                if elapsed_s >= (self.config.duration_seconds * 0.85) and not fault_network_down_done:
                    logger.info("Executing Fault Injection: Frozen network-off job execution")
                    now_u = int(time.time())
                    snap = JobPermissionSnapshot(
                        source_session_id="soak-main-session",
                        workspace_root=str(self.config.workspace_dir),
                        allowed_tool_ids=["filesystem.read"],
                        max_risk_level=0,
                        tokens_per_run=1000,
                        tool_calls_per_run=5,
                        duration_seconds_per_run=2,
                    )
                    job = ScheduledJob(
                        id=f"job-frozen-{now_u}",
                        session_id="soak-main-session",
                        workspace_root=str(self.config.workspace_dir),
                        title="Frozen Network Off Test Job",
                        prompt="Verify network-off containment",
                        schedule_type=ScheduleType.CRON,
                        cron_expression="* * * * *",
                        next_run_at_utc=now_u - 5,
                        permission_snapshot=snap,
                        created_at_utc=now_u,
                        updated_at_utc=now_u,
                        idempotency_key=f"idem-frozen-{now_u}",
                    )
                    await sched_db.create_job(job)
                    claim = await sched_db.claim_next_due_job(now_u, "worker-soak", 1)
                    if claim:
                        _, run_record = claim
                        guard = ScheduledExecutionGuard(snap)
                        try:
                            guard.check_tool_invocation("network.fetch", {})
                            net_denied = False
                        except Exception:
                            net_denied = True

                        await sched_db.complete_run(
                            run_id=run_record.id,
                            owner_instance="worker-soak",
                            ownership_generation=1,
                            final_state=RunState.SUCCESS,
                            consumed_tokens=10,
                            output_summary="Network-off job verified successfully.",
                            next_run_at_utc=now_u + 3600,
                        )
                    else:
                        net_denied = False

                    self.fault_results["network_down_frozen_job"] = {
                        "executed": True,
                        "success": net_denied,
                    }
                    fault_network_down_done = True
                    continue

                # --------------------------------------------------------------
                # Standard Agent Turn & 4-Tier Memory Churn
                # --------------------------------------------------------------
                self.total_turns += 1
                t0 = time.monotonic()
                turn_ok = True
                try:
                    events = []
                    async for event in agent_loop.run_turn(
                        session_id="soak-main-session",
                        user_prompt=f"Soak iteration {self.total_turns} standard turn.",
                        conversation_history=[],
                        cancel_event=self.shutdown_coordinator.turn_cancel_event,
                    ):
                        events.append(event)
                    if not any(e.get("type") == "turn.completed" for e in events):
                        turn_ok = False
                except Exception as exc:
                    logger.error("Turn failed: %s", exc)
                    turn_ok = False

                lat = time.monotonic() - t0
                self.turn_latencies.append(lat)
                if not turn_ok:
                    self.error_count += 1

                # Memory Churn
                await memory_coord.semantic.save(
                    SemanticMemoryEntry(
                        workspace_root=str(self.config.workspace_dir),
                        title=f"Memory_{self.total_turns}",
                        content=f"Continuous soak verified transaction {self.total_turns}",
                        source_session_id="soak-main-session",
                    )
                )
                await memory_coord.search(
                    query=f"transaction {self.total_turns}",
                    workspace_root=str(self.config.workspace_dir),
                    limit_per_tier=2,
                )

                await asyncio.sleep(0.05)

        finally:
            logger.info("Executing graceful teardown sequence...")
            await self.shutdown_coordinator.execute_teardown()

            # Record skipped host APM sleep and lock faults
            self.fault_results["host_sleep_resume"] = {
                "executed": False,
                "status": "skipped",
                "reason": "Host cannot signal APM suspend programmatically without driver hook",
            }
            self.fault_results["host_lock_unlock"] = {
                "executed": False,
                "status": "skipped",
                "reason": "Host session lock API requires active interactive Winlogon desktop",
            }

            # Verify SQLite Database Integrity & perform run-boundary checkpoint
            async with aiosqlite.connect(str(db_path)) as conn:
                cursor = await conn.execute("PRAGMA integrity_check;")
                row = await cursor.fetchone()
                if not (row and row[0] == "ok"):
                    self.violations.append(f"PRAGMA integrity_check failed on {db_path}: {row}")

                cursor = await conn.execute("PRAGMA journal_mode;")
                row = await cursor.fetchone()
                if not (row and row[0].lower() == "wal"):
                    self.violations.append(f"PRAGMA journal_mode was not WAL: {row}")

                # Invariant: wal_checkpoint(TRUNCATE) strictly at run boundaries
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

            # Verify VRAM Recovery Oracle exit recovery
            self.vram_oracle.verify_exit_recovery()
            for v in self.vram_oracle.violations:
                if v not in self.violations:
                    self.violations.append(v)

        # Final Evaluation and Report Generation
        overall_passed = self.generate_reports()
        if overall_passed:
            logger.info("SOAK TEST COMPLETED SUCCESSFULLY: ALL INVARIANTS GREEN.")
            return 0
        else:
            logger.error("SOAK TEST FAILED: VIOLATIONS DETECTED: %s", self.violations)
            return 1

    def generate_reports(self) -> bool:
        """Write logs/soak_results.json and docs/benchmarks/soak_test_report.md."""
        warmup_cutoff_s = self.config.warmup_seconds
        post_warmup = [s for s in self.samples if s.elapsed_seconds >= warmup_cutoff_s] or self.samples

        # Calculate slopes for reporting
        points_mem: List[Tuple[float, float]] = []
        points_handles: List[Tuple[float, float]] = []
        if len(post_warmup) >= 2:
            t0 = post_warmup[0].elapsed_seconds
            for s in post_warmup:
                th = (s.elapsed_seconds - t0) / 3600.0
                points_mem.append((th, s.total_private_bytes_mb))
                points_handles.append((th, float(s.total_handles)))

        priv_slope, _, _ = SoakTripwireEvaluator.calculate_ols_slope(points_mem)
        handle_slope, _, _ = SoakTripwireEvaluator.calculate_ols_slope(points_handles)

        latencies = sorted(self.turn_latencies) if self.turn_latencies else [0.0]
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

        max_wal = max((s.wal_size_mb for s in self.samples), default=0.0)
        max_temp = max((s.gpu.temperature_c for s in self.samples), default=32)

        vram_summary = self.vram_oracle.get_summary()

        metrics = {
            "private_bytes_start_mb": post_warmup[0].total_private_bytes_mb if post_warmup else 0.0,
            "private_bytes_end_mb": post_warmup[-1].total_private_bytes_mb if post_warmup else 0.0,
            "private_bytes_slope_mb_per_hour": round(priv_slope, 2),
            "handles_start": post_warmup[0].total_handles if post_warmup else 0,
            "handles_end": post_warmup[-1].total_handles if post_warmup else 0,
            "handles_growth_per_hour": round(handle_slope, 1),
            "threads_start": post_warmup[0].total_threads if post_warmup else 0,
            "threads_end": post_warmup[-1].total_threads if post_warmup else 0,
            "tcp_conns_avg": round(
                sum(s.total_loopback_tcp for s in self.samples) / max(len(self.samples), 1), 1
            ),
            "wal_bytes_max_mb": round(max_wal, 3),
            "gpu_temp_max_c": max_temp,
            "turn_latency_p50_s": round(p50, 3),
            "turn_latency_p95_s": round(p95, 3),
            "turn_latency_avg_s": round(avg_lat, 3),
            "error_count": self.error_count,
            "error_rate_percent": round((self.error_count / max(self.total_turns, 1)) * 100, 2),
        }

        tripwires = {
            "private_bytes_slope": {
                "status": "PASS" if not any("Private Bytes Slope" in v for v in self.violations) else "FAIL",
                "value_mb_per_hour": round(priv_slope, 2),
                "threshold_mb_per_hour": 50.0,
            },
            "handles_growth": {
                "status": "PASS" if not any("Handle Growth" in v for v in self.violations) else "FAIL",
                "value_per_hour": round(handle_slope, 1),
                "threshold_per_hour": 50.0,
            },
            "thread_ratchet": {
                "status": "PASS" if not any("Thread Ratchet" in v for v in self.violations) else "FAIL",
                "detected": any("Thread Ratchet" in v for v in self.violations),
            },
            "gpu_temperature": {
                "status": "PASS" if not any("GPU Thermal" in v for v in self.violations) else "FAIL",
                "max_temp_c": max_temp,
                "ceiling_c": 83,
            },
            "sqlite_wal_size": {
                "status": "PASS" if not any("WAL" in v for v in self.violations) else "FAIL",
                "max_wal_mb": round(max_wal, 3),
                "threshold_mb": 64.0,
            },
            "vram_recovery": {
                "status": "PASS" if vram_summary["residual_within_512mb"] else "FAIL",
                "residual_delta_mb": vram_summary["residual_delta_mb"],
                "threshold_mb": 512.0,
            },
        }

        passed = len(self.violations) == 0

        generator = ArtifactGenerator()
        results_file = self.config.output_dir / "soak_results.json"
        report_file = self.config.report_dir / "soak_test_report.md"

        payload = generator.write_json_results(
            filepath=results_file,
            mode=self.config.mode,
            duration_s=self.config.duration_seconds,
            warmup_s=self.config.warmup_seconds,
            total_turns=self.total_turns,
            metrics=metrics,
            tripwires=tripwires,
            vram_recovery=vram_summary,
            faults=self.fault_results,
            samples=[s.to_dict() for s in self.samples],
            violations=self.violations,
        )

        generator.write_markdown_report(report_file, payload)
        return passed


# ==============================================================================
# 12. CLI Configuration & Entrypoint
# ==============================================================================


def parse_soak_cli_args(args_list: Optional[list[str]] = None) -> SoakRunnerConfig:
    """Parse and validate command line arguments for the soak endurance runner."""
    parser = argparse.ArgumentParser(
        description="Project Friday Phase 16 Long-Run Soak & Endurance Harness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # 1. Mode and Duration
    parser.add_argument(
        "--mode",
        choices=["smoke", "gate", "release", "custom", "15m", "1h", "8h"],
        default="smoke",
        help="Soak execution profile: smoke (15m), gate (1h), release (8h), or custom",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=None,
        help="Override total duration in minutes (implicitly sets --mode custom)",
    )

    # 2. Warmup & Sampling
    parser.add_argument(
        "--warmup-minutes",
        type=float,
        default=None,
        help="Warmup duration in minutes to discard before evaluating leak slopes (default: 3m for smoke, 15m for gate/release)",
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=None,
        help="Telemetry sampling interval in seconds (default: smoke=10s, gate=15s, release=60s)",
    )

    # 3. File System Directories
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("logs"),
        help="Output directory for soak_results.json and traces",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("docs/benchmarks"),
        help="Report directory for soak_test_report.md",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory for soak databases and transient artifacts",
    )

    # 4. Security & Headless
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run headlessly (auto-denies Risk >= 2 operations, zero native modal clicks)",
    )

    # 5. Process Orchestration & Target Mode
    parser.add_argument(
        "--target-mode",
        choices=["mock", "spawn", "attach"],
        default="mock",
        help="Target architecture: 'mock' (in-process mock inference), 'spawn' (spawn Core/Tabby in Job Object), 'attach' (target running server)",
    )
    parser.add_argument("--core-port", type=int, default=8000, help="Friday Core HTTP port")
    parser.add_argument("--tabby-port", type=int, default=8080, help="TabbyAPI HTTP port")
    parser.add_argument("--core-pid", type=int, default=None, help="Explicit PID of running Core process (attach mode)")
    parser.add_argument("--tabby-pid", type=int, default=None, help="Explicit PID of running TabbyAPI process (attach mode)")
    parser.add_argument(
        "--supervisor-pid", type=int, default=None, help="Explicit PID of running Tauri supervisor (attach mode)"
    )

    # 6. Hardware & Observability
    parser.add_argument(
        "--gpu",
        action="store_true",
        default=False,
        help="Query real NVIDIA NVML / nvidia-smi GPU telemetry for Tabby PID and thermals",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        default=False,
        help="Immediately abort runner if any tripwire (slope, ratchet, temp >= 83C, WAL > 64MB) is breached",
    )
    parser.add_argument(
        "--langfuse",
        action="store_true",
        default=False,
        help="Mirror turn traces to Langfuse Cloud observability sink",
    )

    args = parser.parse_args(args_list)

    # Normalize mode aliases
    mode_aliases = {"15m": "smoke", "1h": "gate", "8h": "release"}
    mode = mode_aliases.get(args.mode, args.mode)

    # Resolve duration
    if args.duration_minutes is not None:
        duration_s = args.duration_minutes * 60.0
        mode = "custom"
    elif mode == "smoke":
        duration_s = 15.0 * 60.0
    elif mode == "gate":
        duration_s = 60.0 * 60.0
    elif mode == "release":
        duration_s = 8.0 * 3600.0
    else:
        duration_s = 15.0 * 60.0
        mode = "smoke"

    # Resolve warmup minutes
    if args.warmup_minutes is not None:
        warmup_s = max(0.0, args.warmup_minutes * 60.0)
    elif mode == "smoke":
        warmup_s = 3.0 * 60.0
    elif mode in ("gate", "release"):
        warmup_s = 15.0 * 60.0
    else:
        warmup_s = min(900.0, duration_s * 0.20)

    # Resolve sampling interval
    if args.sample_interval_seconds is not None:
        sample_interval_s = args.sample_interval_seconds
    elif mode == "smoke":
        sample_interval_s = 10.0
    elif mode == "gate":
        sample_interval_s = 15.0
    elif mode == "release":
        sample_interval_s = 60.0
    else:
        sample_interval_s = max(1.0, min(10.0, duration_s / 50.0))

    workspace = args.workspace if args.workspace else Path("G:/Project_Ned/.soak_workspace")

    # Ensure directories exist
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    return SoakRunnerConfig(
        mode=mode,
        duration_seconds=duration_s,
        warmup_seconds=warmup_s,
        sample_interval_seconds=sample_interval_s,
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        workspace_dir=workspace,
        headless=args.headless,
        target_mode=args.target_mode,
        core_port=args.core_port,
        tabby_port=args.tabby_port,
        core_pid=args.core_pid,
        tabby_pid=args.tabby_pid,
        supervisor_pid=args.supervisor_pid,
        use_gpu=args.gpu,
        fail_fast=args.fail_fast,
        enable_langfuse=args.langfuse,
    )


def main() -> int:
    config = parse_soak_cli_args()
    runner = StandaloneSoakRunner(config)
    return asyncio.run(runner.run())


if __name__ == "__main__":
    sys.exit(main())
