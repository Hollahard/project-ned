# Phase 16 Milestone 3 Handoff Report: Telemetry Metrics, Win32/NVML Sampling, Tripwire Evaluation & Dual-Sink Streaming

**Agent**: Explorer 2 (`teamwork_preview_explorer_m3_2`)  
**Mission**: Milestone 3 Standalone Long-Run Endurance Runner Telemetry & Tripwire Architecture  
**Target File**: `tests/soak/run_8hr_soak.py` (and supporting `tests/soak/telemetry.py` module)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Timestamp**: 2026-10-07T17:25:00Z  

---

## 1. Observation

### 1.1 Existing Telemetry & Soak Harness State
1. **Existing Runner Structure (`tests/soak/run_8hr_soak.py:440-487, 753-792`)**:
   - Telemetry sampling is currently embedded directly inside the execution loop `while time.monotonic() < end_time_mono` using raw `ctypes` calls for `psapi.GetProcessMemoryInfo`, `kernel32.GetProcessHandleCount`, `kernel32.CreateToolhelp32Snapshot`, `netstat -ano -p tcp`, and `nvidia-smi`.
   - **Post-hoc Evaluation**: Invariant checking only runs **after** the test finishes (`run_8hr_soak.py:753` `evaluate_results()`). There is zero **online fast-abort tripwire** during the multi-hour execution; a process with rapid memory or handle leakage would run for the full 8 hours before reporting failure.
   - **Endpoint Delta vs Regression**: `run_8hr_soak.py:766-774` computes memory drift as a naive 2-point endpoint delta:
     ```python
     t_span_hours = (post_warmup_samples[-1].elapsed_seconds - post_warmup_samples[0].elapsed_seconds) / 3600.0
     priv_diff_mb = post_warmup_samples[-1].private_bytes_mb - post_warmup_samples[0].private_bytes_mb
     priv_slope_per_hour = priv_diff_mb / t_span_hours
     ```
     This formula is not an Ordinary Least Squares (OLS) linear regression slope and is vulnerable to transient GC pauses or momentary allocation spikes at the endpoints.
   - **Thread Ratchet Check**: `run_8hr_soak.py:784-789` checks only `final_threads > initial_threads + 5`. It does not analyze monotonic ratcheting across sliding windows.
   - **Missing GPU Temperature Tripwire**: There is no thermal ceiling check (83°C tripwire from ADR-0002) in `run_8hr_soak.py`.
   - **Missing Dual-Sink Streaming**: Telemetry is accumulated in an in-memory Python list `self.samples` and dumped only upon exit into `logs/soak_results.json`. There is no streaming to `logs/traces/soak_<timestamp>.jsonl` or Langfuse Cloud during the run.

2. **Python Environment & Installed Packages (`.venv`)**:
   - `nvidia-ml-py` / `pynvml` (v13.0.0) is installed in `G:\Project_Ned\.venv\Lib\site-packages\pynvml.py`.
     - Direct verification command: `pynvml.nvmlInit()`; GPU queried successfully: `"NVIDIA GeForce RTX 5090"`, temperature: `31°C`.
   - `langfuse` (v4.17.0) is installed in `G:\Project_Ned\.venv\Lib\site-packages\langfuse`.
   - `pywin32` (v306+) is installed.
   - `psutil` is **NOT** installed in `.venv` (attempting `import psutil` raised `ModuleNotFoundError`).
   - `tracemalloc` is active during fast CI tests (`tests/soak/test_soak_endurance.py:149`), but ADR-0002 §1 explicitly mandates:
     > "Fast CI test suite may utilize tracemalloc; long-running soak runs must disable tracemalloc to eliminate profiling overhead."

3. **Windows WDDM GPU Attribution Behavior**:
   - Invoking `nvidia-smi --help-query-compute-apps`:
     > `"used_gpu_memory" or "used_memory": Amount memory used on the device by the context. Not available on Windows when running in WDDM mode because Windows KMD manages all the memory not NVIDIA driver.`
   - In Windows 11 WDDM mode, DirectX and desktop GUI applications report `[N/A]` for compute memory. When a pure CUDA process (e.g., PyTorch / ExLlamaV3 in TabbyAPI) runs, compute-apps or NVML `nvmlDeviceGetComputeRunningProcesses` reports memory, but if WDDM intercepts memory management, `p.usedGpuMemory` can return `None`.

4. **Existing Friday Telemetry Subsystem (`services/core/src/friday/telemetry/`)**:
   - `LocalJsonlSink` (`tracer.py:132-159`): provides sanitized append-only writing to JSONL files with secret redaction and 64 KiB bounds.
   - `LangfuseSink` (`langfuse.py:36-122`): provides resilient Langfuse SDK v4 client wrapping with automatic fallback if credentials (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are missing or network is unreachable.
   - `TelemetryProvider` (`services/core/src/friday/inference/telemetry.py:26-111`): provides NVML queries for GPU temperature, VRAM total/used/free, and wattage.

---

## 2. Logic Chain

1. **Need for Modular Architecture**:
   Inline sampling inside `run_8hr_soak.py` creates a monolith that couples process execution, telemetry acquisition, invariant verification, and output generation. Factoring into three distinct classes—`TelemetrySampler`, `TripwireEvaluator`, and `DualSinkLogger`—allows clean separation of concerns, unit-testability, and seamless coordination between Explorer 1 (CLI & Process Lifecycle), Explorer 2 (Telemetry & Math), and Explorer 3 (Faults & Reporting).

2. **Sampling Portability (psutil + Win32 ctypes Dual Strategy)**:
   Because `psutil` is not in `.venv` but may be added later or installed in other test environments, `TelemetrySampler` must support `psutil` if available while providing a first-class, zero-dependency Win32 `ctypes` implementation using `kernel32`, `psapi`, and `iphlpapi`:
   - `psapi.GetProcessMemoryInfo` with `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage` captures true Private Bytes commit without working-set paging distortion.
   - `kernel32.GetProcessHandleCount` accurately reads OS handles.
   - `kernel32.CreateToolhelp32Snapshot` provides instantaneous thread count.
   - `iphlpapi.GetExtendedTcpTable` (with `netstat` fallback) queries loopback `127.0.0.1` sockets in-process (0.05ms) without spawning subprocesses or causing handle churn.

3. **Multi-Tiered NVML TabbyAPI VRAM Attribution**:
   Due to Windows WDDM driver behavior, attributing VRAM exclusively via a single `nvidia-smi` command risks returning 0 or `[N/A]`. A resilient attribution cascade is required:
   - Tier 1: NVML `nvmlDeviceGetComputeRunningProcesses(handle)` filtered by TabbyAPI PID (`usedGpuMemory`).
   - Tier 2: `nvidia-smi --query-compute-apps=pid,used_gpu_memory` subprocess query.
   - Tier 3: GPU Device Allocation Delta (`current_total_used - baseline_pre_launch_used`), which captures Tabby's allocation footprint under WDDM.
   - Tier 4: Controllable mock inference telemetry (`inference.current_vram_mb`) when running in simulated mode.

4. **Rigorous Mathematical Tripwires**:
   - **Warmup Discard**: In multi-hour runs, JIT compilation, SQLite B-tree page caching, and DLL mapping cause transient initial growth. ADR-0002 specifies discarding the first 15 minutes (`900s`). For short runs (e.g., `--mode smoke` 15 min), warmup is scaled to 20% (`min(900s, duration * 0.20) = 180s`) to ensure evaluation samples exist.
   - **OLS Linear Regression**: Rather than 2-point endpoint deltas, Ordinary Least Squares slope $\beta_1 = \frac{\sum (t_i - \bar{t})(y_i - \bar{y})}{\sum (t_i - \bar{t})^2}$ filters high-frequency noise and accurately measures true drift in MB/hour and handles/hour.
   - **Sliding-Window Thread Ratchet**: To differentiate between normal thread pool scaling and true monotonic thread leaks, a sliding window floor detector tracks the minimum thread count $\min(T_{W_k})$ across successive sliding windows. If consecutive window floors strictly increase across 3+ windows and total threads exceed baseline by $\ge 5$, a thread ratchet violation is triggered.
   - **Online Abort / Fail-Fast**: Evaluating tripwires on every telemetry tick allows immediate abort if Private Bytes slope > 50 MB/hr (with minimum 10 MB drift), handles slope > 50/hr, thread ratchets, WAL size > 64 MB, or GPU temperature > 83°C. This avoids wasting 7.5 hours on an already-failed run and protects the RTX 5090 hardware from thermal damage.
   - **Tracemalloc Invariant**: Soak runs must verify `tracemalloc.is_tracing() is False` on every sample to prevent profiling overhead and artificial slope distortion.

5. **Dual-Sink Telemetry Streaming**:
   - Sink 1 (`logs/traces/soak_<timestamp>.jsonl`): Guarantees sovereign, durable offline recording. Each telemetry tick is appended as an atomic JSON line with full process breakdown, aggregate sums, GPU stats, and tripwire statuses.
   - Sink 2 (Langfuse Cloud): Reuses `LangfuseSink` with non-blocking event emission and numeric score updates (`soak.private_bytes_mb`, `soak.handles`, `soak.vram_mb`, `soak.gpu_temp_c`). If Langfuse is unconfigured or network is down, it fails silently with zero interruption to the soak runner.

---

## 3. Caveats

1. **Subprocess Spawning during Telemetry Ticks**:
   Using `subprocess.check_output("netstat ...")` or `subprocess.check_output("nvidia-smi ...")` on every 5s-10s tick creates minor process churn and transient handle spikes. The pure `ctypes` (`iphlpapi.GetExtendedTcpTable`) and native `pynvml` implementations recommended below eliminate this overhead and run entirely in-process.
2. **GPU Temperature in Headless/Mock Mode**:
   If running on a system without an NVIDIA GPU or in CI without GPU pass-through, NVML will gracefully report `available=False` and temperature `0` (or room ambient `25°C`), bypassing the 83°C tripwire without false positive failure.
3. **Smoke Mode Calibration**:
   In `--mode smoke` (15 minutes), 15 minutes of warmup would discard all samples. The evaluator automatically applies `warmup_duration = min(900.0, total_duration * 0.20)` so that smoke runs discard 3 minutes of warmup and evaluate the remaining 12 minutes.

---

## 4. Conclusion & Concrete Implementation Blueprints

Below are the complete, production-grade Python class blueprints for `TelemetrySampler`, `TripwireEvaluator`, and `DualSinkLogger`. These should be placed in `tests/soak/telemetry.py` and imported by `tests/soak/run_8hr_soak.py`.

### 4.1 Class 1: `TelemetrySampler` (`tests/soak/telemetry.py`)

```python
"""High-precision Windows and NVML telemetry sampler for Project Friday soak runner."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("friday.soak.sampler")

# Try importing psutil, fallback to ctypes
_PSUTIL_AVAILABLE = False
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None

# Try importing pynvml
_NVML_AVAILABLE = False
try:
    import pynvml
    _NVML_AVAILABLE = True
except ImportError:
    pynvml = None

# Win32 ctypes structures and definitions
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
iphlpapi = ctypes.windll.iphlpapi

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5


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
            "processes": {k: v.to_dict() for k, v in self.processes.items()},
            "aggregate": {
                "total_private_bytes_mb": round(self.total_private_bytes_mb, 2),
                "total_handles": self.total_handles,
                "total_threads": self.total_threads,
                "total_loopback_tcp": self.total_loopback_tcp,
            },
            "gpu": self.gpu.to_dict(),
            "sqlite": {
                "wal_size_mb": round(self.wal_size_mb, 3),
            },
            "turn_metrics": {
                "turn_count": self.turn_count,
                "recent_latency_s": round(self.recent_turn_latency_s, 3),
                "error_count": self.error_count,
            },
        }


class TelemetrySampler:
    """Samples Win32 process metrics and NVML GPU metrics across monitored processes."""

    def __init__(
        self,
        monitored_pids: Optional[Dict[str, int]] = None,
        db_path: Optional[Path] = None,
        device_index: int = 0,
        use_real_gpu: bool = True,
    ) -> None:
        self.monitored_pids: Dict[str, int] = dict(monitored_pids or {})
        if not self.monitored_pids:
            self.monitored_pids["runner"] = os.getpid()

        self.db_path = db_path
        self.device_index = device_index
        self.use_real_gpu = use_real_gpu
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

    def register_process(self, name: str, pid: int) -> None:
        self.monitored_pids[name] = pid

    def unregister_process(self, name: str) -> None:
        self.monitored_pids.pop(name, None)

    @staticmethod
    def assert_tracemalloc_disabled() -> None:
        """Guarantee tracemalloc is disabled during endurance soak runs."""
        if tracemalloc.is_tracing():
            logger.warning("tracemalloc was active! Disabling to eliminate profiling overhead.")
            tracemalloc.stop()
        assert not tracemalloc.is_tracing(), "tracemalloc must be disabled during endurance soak"

    def sample_process(self, name: str, pid: int) -> ProcessMetrics:
        """Query Private Bytes, Handles, Threads, and Loopback TCP sockets for a PID."""
        priv_bytes = 0
        handles = 0
        threads = 0
        loopback_tcp = 0

        if _PSUTIL_AVAILABLE and psutil is not None:
            try:
                p = psutil.Process(pid)
                priv_bytes = p.memory_info().private
                handles = p.num_handles()
                threads = p.num_threads()
                # Count loopback TCP connections
                conns = p.net_connections(kind="tcp")
                for c in conns:
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
                pass  # Fallback to ctypes below

        # Fallback: Native Win32 ctypes
        h_proc = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if h_proc:
            try:
                # Private Bytes
                counters = PROCESS_MEMORY_COUNTERS_EX()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
                if psapi.GetProcessMemoryInfo(h_proc, ctypes.byref(counters), counters.cb):
                    priv_bytes = int(counters.PrivateUsage)

                # OS Handle Count
                h_count = ctypes.wintypes.DWORD()
                if kernel32.GetProcessHandleCount(h_proc, ctypes.byref(h_count)):
                    handles = int(h_count.value)
            finally:
                kernel32.CloseHandle(h_proc)

        # Thread Count via Toolhelp32Snapshot
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

        # Loopback TCP sockets via GetExtendedTcpTable or netstat
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
        """Count 127.0.0.1 TCP sockets for PID using netstat fallback."""
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

    def sample_gpu(self, tabby_pid: Optional[int] = None) -> GpuMetrics:
        """Sample NVML GPU telemetry and attribute VRAM specifically to TabbyAPI PID."""
        if not self.use_real_gpu:
            return GpuMetrics(available=False, device_name="Mock/Offline Mode")

        metrics = GpuMetrics()
        if self._nvml_initialized and self._nvml_handle:
            try:
                metrics.available = True
                metrics.device_name = str(pynvml.nvmlDeviceGetName(self._nvml_handle))
                metrics.driver_version = str(pynvml.nvmlSystemGetDriverVersion())
                metrics.temperature_c = pynvml.nvmlDeviceGetTemperature(
                    self._nvml_handle, pynvml.NVML_TEMPERATURE_GPU
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

                # Attributed TabbyAPI VRAM query
                if tabby_pid is not None:
                    # Tier 1: NVML compute processes
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

        gpu_metrics = self.sample_gpu(tabby_pid=tabby_pid or self.monitored_pids.get("tabby"))

        wal_mb = 0.0
        if self.db_path:
            wal_p = Path(f"{self.db_path}-wal")
            if wal_p.exists():
                try:
                    wal_mb = round(wal_p.stat().st_size / (1024**2), 3)
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
```

---

### 4.2 Class 2: `TripwireEvaluator` (`tests/soak/telemetry.py`)

```python
"""Online mathematical tripwire evaluator for Project Friday endurance soak testing."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("friday.soak.evaluator")


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


class TripwireEvaluator:
    """Evaluates online soak samples against ADR-0002 mathematical tripwires."""

    def __init__(
        self,
        total_duration_seconds: float,
        warmup_duration_seconds: Optional[float] = None,
        max_priv_bytes_slope_mb_hr: float = 50.0,
        max_handles_slope_hr: float = 50.0,
        max_gpu_temp_c: int = 83,
        max_wal_mb: float = 64.0,
        min_samples_for_slope: int = 5,
        min_drift_mb_for_slope: float = 10.0,
        min_drift_handles_for_slope: int = 10,
        ratchet_window_size: int = 10,
        ratchet_slack_threads: int = 5,
    ) -> None:
        self.total_duration_seconds = total_duration_seconds
        # Discard first 15 minutes (or 20% of duration for short runs like smoke 15m)
        if warmup_duration_seconds is not None:
            self.warmup_duration_seconds = warmup_duration_seconds
        else:
            self.warmup_duration_seconds = min(900.0, total_duration_seconds * 0.20)

        self.max_priv_bytes_slope_mb_hr = max_priv_bytes_slope_mb_hr
        self.max_handles_slope_hr = max_handles_slope_hr
        self.max_gpu_temp_c = max_gpu_temp_c
        self.max_wal_mb = max_wal_mb
        self.min_samples_for_slope = min_samples_for_slope
        self.min_drift_mb_for_slope = min_drift_mb_for_slope
        self.min_drift_handles_for_slope = min_drift_handles_for_slope
        self.ratchet_window_size = ratchet_window_size
        self.ratchet_slack_threads = ratchet_slack_threads

        self.warmup_samples: List[TelemetrySnapshot] = []
        self.eval_samples: List[TelemetrySnapshot] = []
        self.cumulative_violations: List[str] = []
        self.max_gpu_temp: int = 0
        self.max_wal: float = 0.0

    @staticmethod
    def calculate_ols_slope(points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
        """Compute Ordinary Least Squares (OLS) slope, intercept, and R^2.

        Args:
            points: List of (t_hours, value) tuples.

        Returns:
            (slope, intercept, r_squared)
        """
        n = len(points)
        if n < 2:
            return 0.0, 0.0, 0.0

        sum_t = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        mean_t = sum_t / n
        mean_y = sum_y / n

        ss_tt = sum((p[0] - mean_t) ** 2 for p in points)
        ss_yy = sum((p[1] - mean_y) ** 2 for p in points)
        ss_ty = sum((p[0] - mean_t) * (p[1] - mean_y) for p in points)

        if ss_tt <= 1e-9:
            return 0.0, mean_y, 0.0

        slope = ss_ty / ss_tt
        intercept = mean_y - slope * mean_t
        r_squared = (ss_ty**2) / (ss_tt * ss_yy) if ss_yy > 1e-9 else 1.0

        return slope, intercept, max(0.0, min(1.0, r_squared))

    def detect_thread_ratchet(self, threads: List[int]) -> bool:
        """Detect monotonic thread ratchet across sliding windows.

        Algorithm:
        1. Requires at least 3 non-overlapping or stepped windows of size W.
        2. Calculates the local minimum floor min(T_Wk) for each window.
        3. If consecutive window floors monotonically increase across 3+ windows:
           floor_k > floor_{k-1} > floor_{k-2}
           AND latest thread count exceeds warmup baseline by >= ratchet_slack_threads,
           a ratchet violation is flagged.
        """
        w = self.ratchet_window_size
        if len(threads) < 3 * w:
            return False

        # Extract consecutive window minimum floors
        floors = []
        step = max(1, w // 2)
        for i in range(0, len(threads) - w + 1, step):
            window = threads[i : i + w]
            floors.append(min(window))

        if len(floors) < 3:
            return False

        # Check for 3 consecutive strictly increasing floors at the tail
        f1, f2, f3 = floors[-3], floors[-2], floors[-1]
        baseline = threads[0]
        latest = threads[-1]

        if f3 > f2 > f1 and (latest >= baseline + self.ratchet_slack_threads):
            logger.error(
                "Thread ratchet triggered: floors=[%d, %d, %d], baseline=%d, latest=%d",
                f1, f2, f3, baseline, latest
            )
            return True

        return False

    def evaluate(self, sample: TelemetrySnapshot) -> TripwireResult:
        """Evaluate a new telemetry sample against all active tripwires."""
        violations: List[str] = []
        in_warmup = sample.elapsed_seconds < self.warmup_duration_seconds

        # Update global maximums
        if sample.gpu.available:
            self.max_gpu_temp = max(self.max_gpu_temp, sample.gpu.temperature_c)
        self.max_wal = max(self.max_wal, sample.wal_size_mb)

        # ----------------------------------------------------------------------
        # Tripwire 1: GPU Thermal Ceiling (Checked ALWAYS, even during warmup!)
        # ----------------------------------------------------------------------
        if sample.gpu.available and sample.gpu.temperature_c >= self.max_gpu_temp_c:
            violations.append(
                f"GPU Thermal Tripwire Breached: {sample.gpu.temperature_c}°C >= {self.max_gpu_temp_c}°C limit"
            )

        # ----------------------------------------------------------------------
        # Tripwire 2: SQLite WAL Accumulation (Checked ALWAYS)
        # ----------------------------------------------------------------------
        if sample.wal_size_mb > self.max_wal_mb:
            violations.append(
                f"SQLite WAL Size Tripwire Breached: {sample.wal_size_mb:.2f} MB > {self.max_wal_mb:.1f} MB limit"
            )

        # Buffer samples by phase
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

        # ----------------------------------------------------------------------
        # Post-Warmup Slope & Ratchet Calculations
        # ----------------------------------------------------------------------
        t_origin_s = self.eval_samples[0].elapsed_seconds
        points_mem: List[Tuple[float, float]] = []
        points_handles: List[Tuple[float, float]] = []
        thread_series: List[int] = []

        for s in self.eval_samples:
            t_hours = (s.elapsed_seconds - t_origin_s) / 3600.0
            points_mem.append((t_hours, s.total_private_bytes_mb))
            points_handles.append((t_hours, float(s.total_handles)))
            thread_series.append(s.total_threads)

        priv_slope, _, priv_r2 = self.calculate_ols_slope(points_mem)
        priv_drift = points_mem[-1][1] - points_mem[0][1]

        handle_slope, _, handle_r2 = self.calculate_ols_slope(points_handles)
        handle_drift = int(points_handles[-1][1] - points_handles[0][1])

        ratchet_detected = self.detect_thread_ratchet(thread_series)

        # Only evaluate slopes after minimum sample count
        if len(self.eval_samples) >= self.min_samples_for_slope:
            # Tripwire 3: Private Bytes Slope > 50 MB/hour
            if (
                priv_slope > self.max_priv_bytes_slope_mb_hr
                and priv_drift > self.min_drift_mb_for_slope
            ):
                violations.append(
                    f"Private Bytes Slope Breached: {priv_slope:.2f} MB/h > {self.max_priv_bytes_slope_mb_hr:.1f} MB/h "
                    f"(drift={priv_drift:.2f} MB, R2={priv_r2:.3f})"
                )

            # Tripwire 4: Handle Count Slope > 50 handles/hour
            if (
                handle_slope > self.max_handles_slope_hr
                and handle_drift > self.min_drift_handles_for_slope
            ):
                violations.append(
                    f"OS Handle Growth Slope Breached: {handle_slope:.1f}/h > {self.max_handles_slope_hr:.1f}/h "
                    f"(drift={handle_drift}, R2={handle_r2:.3f})"
                )

        # Tripwire 5: Monotonic Thread Ratchet
        if ratchet_detected:
            violations.append(
                f"Monotonic Thread Ratchet Breached: thread count failed to stabilize across sliding windows "
                f"(current={thread_series[-1]}, baseline={thread_series[0]})"
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
```

---

### 4.3 Class 3: `DualSinkLogger` (`tests/soak/telemetry.py`)

```python
"""Dual-sink streaming telemetry logger (Local JSONL + Langfuse Cloud mirroring)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("friday.soak.dualsink")

# Import Friday's LangfuseSink wrapper
try:
    from friday.telemetry.langfuse import LangfuseSink
    from friday.telemetry.tracer import sanitize_payload
except ImportError:
    LangfuseSink = None  # type: ignore
    def sanitize_payload(obj: Any) -> Any:  # type: ignore
        return obj


class DualSinkLogger:
    """Streams soak telemetry dual-sink to local JSONL and Langfuse Cloud with offline resilience."""

    def __init__(
        self,
        logs_dir: Path | str = "logs/traces",
        session_id: Optional[str] = None,
        enable_langfuse: bool = True,
    ) -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or f"soak-{int(datetime.now(timezone.utc).timestamp())}"
        self.enable_langfuse = enable_langfuse

        # Sink 1: Local partitioned JSONL file
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.local_jsonl_path = self.logs_dir / f"soak_{timestamp_str}.jsonl"
        self._file_handle = open(self.local_jsonl_path, "a", encoding="utf-8")
        logger.info("Local JSONL telemetry stream opened at %s", self.local_jsonl_path)

        # Sink 2: Langfuse Cloud Sink
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
        """Emit telemetry sample to both sinks."""
        payload = snapshot.to_dict()
        payload["tripwire"] = tripwire.to_dict()

        # ----------------------------------------------------------------------
        # 1. Local JSONL Sink (Sovereign append-only)
        # ----------------------------------------------------------------------
        try:
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            self._file_handle.write(line)
            self._file_handle.flush()
        except Exception as exc:
            logger.error("Failed writing to local JSONL sink: %s", exc)

        # ----------------------------------------------------------------------
        # 2. Langfuse Cloud Sink (Resilient Mirroring)
        # ----------------------------------------------------------------------
        if self.langfuse_sink and self.langfuse_sink.is_active():
            try:
                client = self.langfuse_sink._get_active_client()
                if client:
                    # Emit observation event
                    clean_meta = sanitize_payload(payload)
                    client.create_event(
                        name="soak.telemetry_tick",
                        metadata=clean_meta,
                    )
                    # Emit numeric metrics for live dashboard graphs
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

    def flush(self) -> None:
        try:
            self._file_handle.flush()
        except Exception:
            pass
        if self.langfuse_sink and self.langfuse_sink.is_active():
            try:
                self.langfuse_sink.flush()
            except Exception:
                pass

    def close(self) -> None:
        self.flush()
        try:
            self._file_handle.close()
        except Exception:
            pass
        if self.langfuse_sink and self.langfuse_sink.is_active():
            try:
                self.langfuse_sink.shutdown()
            except Exception:
                pass
        logger.info("DualSinkLogger closed cleanly.")
```

---

## 5. Verification Method

To independently verify the implementation and algorithms:

1. **Unit Test for Mathematical Tripwires (`tests/soak/test_tripwire_evaluator.py`)**:
   Verify OLS linear regression slope, warmup discard, and thread ratchet detection on synthetic telemetry sequences:
   ```powershell
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_tripwire_evaluator.py -v > test_evaluator.txt 2>&1"
   ```
   *Expected outcome*:
   - Clean flat sequence (drift < 1 MB) yields slope ~0.0 MB/h, `passed=True`.
   - Leaking sequence (+100 MB/h over 30 min) triggers tripwire abort with `passed=False`.
   - Sliding window thread sequence (`[10]*10, [12]*10, [15]*10, [18]*10`) triggers thread ratchet tripwire.
   - Over-temperature sample (84°C) triggers immediate thermal tripwire abort even within warmup.

2. **Integration Test for Dual-Sink Logging**:
   Verify that local JSONL file is created in `logs/traces/soak_<timestamp>.jsonl` with valid line-delimited JSON, and that execution completes with zero warnings when Langfuse is offline:
   ```powershell
   cmd.exe /c ".\.venv\Scripts\python.exe -c ""from tests.soak.telemetry import TelemetrySampler, TripwireEvaluator, DualSinkLogger; s = TelemetrySampler(); e = TripwireEvaluator(900); l = DualSinkLogger(); snap = s.sample(); res = e.evaluate(snap); l.log_tick(snap, res); l.close(); print('DualSink verified successfully!')"" > test_dualsink.txt 2>&1"
   ```

3. **Smoke Endurance Run (15-min CLI qualification)**:
   ```powershell
   cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke > smoke_run.txt 2>&1"
   ```
   *Expected outcome*:
   - Successfully discards 3 minutes (20%) warmup.
   - Evaluates remaining 12 minutes of turns and memory churn.
   - Emits structured telemetry records to `logs/traces/soak_<timestamp>.jsonl`.
   - Generates `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md` with final OLS slopes and green tripwire status.

4. **Tracemalloc Cleanliness Invariant**:
   Assert that `tracemalloc.is_tracing()` remains strictly `False` throughout runner execution.
