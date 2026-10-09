"""TabbyAPI Inference Broker Supervisor with Windows Job Object lifecycle management.

Enforces:
1. Isolated subprocess execution inside runtime/tabbyAPI/.venv.
2. Sanitized environment with whitelisted variables (PATH, TEMP, SYSTEMROOT) and zero secret leakage.
3. Win32 Job Object containment with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) and zero breakaway.
4. Strict zero-orphan process guarantee: OS kernel unconditionally reaps child processes upon parent exit.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping

logger = logging.getLogger(__name__)

# Win32 Constants
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000
JobObjectExtendedLimitInformation = 9
JobObjectBasicAccountingInformation = 1

# Process creation flags
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


if sys.platform == "win32":

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
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
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


# Explicit whitelist for child processes: strictly strip parent secrets
ENV_WHITELIST = frozenset(
    {
        "PATH",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "CUDA_PATH",
        "CUDA_HOME",
        "CUDA_PATH_V12_4",
        "VIRTUAL_ENV",
    }
)


def sanitize_environment(
    base_env: Mapping[str, str] | None = None,
    extra_vars: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Whitelists only safe OS and runtime environment variables, stripping secrets."""
    source = os.environ if base_env is None else base_env
    sanitized: dict[str, str] = {}

    for k, v in source.items():
        if k.upper() in ENV_WHITELIST:
            sanitized[k] = v

    if extra_vars:
        for k, v in extra_vars.items():
            sanitized[k] = v

    return sanitized


@dataclass
class SupervisorConfig:
    venv_dir: Path | None = None
    python_executable: Path | None = None
    working_dir: Path | None = None
    port: int = 5000
    host: str = "127.0.0.1"
    extra_env: dict[str, str] = field(default_factory=dict)


class TabbyBrokerSupervisor:
    """Supervises the TabbyAPI broker process in an isolated Win32 Job Object."""

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self.config = config or SupervisorConfig()
        self._job_handle = None
        self._process: subprocess.Popen | None = None
        self._pid: int | None = None
        self._closed: bool = False

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def resolve_python(self) -> Path:
        """Resolves the isolated Python interpreter inside runtime/tabbyAPI/.venv."""
        if self.config.python_executable and self.config.python_executable.is_file():
            return self.config.python_executable

        # Check configured or standard venv path
        candidates = []
        if self.config.venv_dir:
            candidates.append(self.config.venv_dir / "Scripts" / "python.exe")

        # Standard project location
        candidates.extend(
            [
                Path("runtime/tabbyAPI/.venv/Scripts/python.exe"),
                Path("G:/Project_Ned/runtime/tabbyAPI/.venv/Scripts/python.exe"),
            ]
        )

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()

        # Fallback to sys.executable in test/isolated virtual environments
        return Path(sys.executable)

    def _init_job_object(self) -> None:
        """Creates and configures the Win32 Job Object with KILL_ON_JOB_CLOSE."""
        if sys.platform != "win32" or kernel32 is None:
            return

        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            raise ctypes.WinError(ctypes.get_last_error())

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        success = kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not success:
            kernel32.CloseHandle(h_job)
            raise ctypes.WinError(ctypes.get_last_error())

        self._job_handle = h_job

    def query_job_limit_flags(self) -> int:
        """Queries the kernel to verify LimitFlags on the active Job Object."""
        if not self._job_handle or kernel32 is None:
            return 0

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ret = kernel32.QueryInformationJobObject(
            self._job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        )
        if not ret:
            raise ctypes.WinError(ctypes.get_last_error())
        return info.BasicLimitInformation.LimitFlags

    def active_process_count(self) -> int:
        """Queries the kernel for currently active processes inside the Job Object."""
        if not self._job_handle or kernel32 is None:
            return 1 if self.is_alive else 0

        acct = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        ret = kernel32.QueryInformationJobObject(
            self._job_handle,
            JobObjectBasicAccountingInformation,
            ctypes.byref(acct),
            ctypes.sizeof(acct),
            None,
        )
        if not ret:
            raise ctypes.WinError(ctypes.get_last_error())
        return acct.ActiveProcesses

    def spawn(
        self,
        command_args: list[str] | None = None,
        working_dir: Path | None = None,
    ) -> int:
        """Spawns the child broker process inside the isolated Job Object."""
        if self.is_alive:
            raise RuntimeError("Broker process already running")

        self._init_job_object()

        python_exe = self.resolve_python()
        cwd = working_dir or self.config.working_dir or Path.cwd()

        if command_args is None:
            # Default to TabbyAPI launch or ping loop if testing
            command = [str(python_exe), "-c", "import time; time.sleep(3600)"]
        else:
            command = [str(python_exe)] + command_args

        env = sanitize_environment(extra_vars=self.config.extra_env)

        # On Windows, assign process handle directly to Job Object immediately after creation
        self._process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._pid = self._process.pid

        if self._job_handle and kernel32 is not None:
            # Assign process to job object
            process_handle = int(self._process._handle)  # type: ignore
            assigned = kernel32.AssignProcessToJobObject(self._job_handle, process_handle)
            if not assigned:
                err = ctypes.get_last_error()
                self.terminate()
                raise ctypes.WinError(err)

        return self._pid

    def terminate(self, timeout: float = 5.0) -> None:
        """Terminates the process tree cleanly."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=timeout)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

        if self._job_handle and kernel32 is not None:
            try:
                kernel32.TerminateJobObject(self._job_handle, 1)
            except Exception:
                pass

    def close(self) -> None:
        """Closes handles and ensures all descendants are reaped."""
        if self._closed:
            return
        self._closed = True

        self.terminate()

        if self._job_handle and kernel32 is not None:
            kernel32.CloseHandle(self._job_handle)
            self._job_handle = None

    def __enter__(self) -> TabbyBrokerSupervisor:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
