"""Windows Job Object and isolated environment cage for friday-skill-host (Phase 10B).

Invariants:
1. Process runs inside a Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
2. Active process limit strictly capped at 1 (no subprocess spawning from child).
3. UI limits applied (cannot display windows, access clipboard, or cover parent modal).
4. Working directory is a clean temporary directory wiped on exit.
5. Environment is an explicit minimal whitelist with zero parent secrets or tokens.
6. If parent terminates, Windows kernel unconditionally terminates the child.
"""

import ctypes
from ctypes import wintypes
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Windows Job Object Flags & Information Classes
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
JobObjectExtendedLimitInformation = 9
JobObjectBasicUIRestrictions = 4
JOB_OBJECT_UILIMIT_ALL = 0xFF

# Minimal environment whitelist for Python execution in cage
SAFE_CAGE_ENV_WHITELIST = {
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "PATH",
    "TEMP",
    "TMP",
    "PYTHONPATH",
    "PYTHONHOME",
    "WINDIR",
}


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


class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [
        ("UIRestrictionsClass", ctypes.c_uint32),
    ]


class WindowsJobCage:
    """Manages Windows Job Object with KILL_ON_JOB_CLOSE, process cap 1, and UI limits."""

    def __init__(self) -> None:
        self._handle = None
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle or handle == 0:
                err = kernel32.GetLastError()
                raise OSError(f"CreateJobObjectW failed with error code {err}")
            self._handle = handle
            self._configure_limits()

    def _configure_limits(self) -> None:
        if not self._handle:
            return
        kernel32 = ctypes.windll.kernel32

        # 1. Extended limits: kill on job close + active process cap = 1
        ext_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ext_info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
        ext_info.BasicLimitInformation.ActiveProcessLimit = 1

        res = kernel32.SetInformationJobObject(
            self._handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(ext_info),
            ctypes.sizeof(ext_info),
        )
        if res == 0:
            err = kernel32.GetLastError()
            raise OSError(f"SetInformationJobObject (ExtendedLimits) failed with error {err}")

        # 2. UI Restrictions: block desktop windows, clipboard, display alterations
        ui_info = JOBOBJECT_BASIC_UI_RESTRICTIONS()
        ui_info.UIRestrictionsClass = JOB_OBJECT_UILIMIT_ALL

        res_ui = kernel32.SetInformationJobObject(
            self._handle,
            JobObjectBasicUIRestrictions,
            ctypes.byref(ui_info),
            ctypes.sizeof(ui_info),
        )
        if res_ui == 0:
            err = kernel32.GetLastError()
            raise OSError(f"SetInformationJobObject (UIRestrictions) failed with error {err}")

        logger.info("Configured Windows Job Object with KILL_ON_CLOSE, process_limit=1, UI_RESTRICTIONS")

    def assign_process(self, process_handle: int) -> None:
        """Assign target process to the Job Object."""
        if not self._handle:
            return
        kernel32 = ctypes.windll.kernel32
        res = kernel32.AssignProcessToJobObject(self._handle, wintypes.HANDLE(process_handle))
        if res == 0:
            err = kernel32.GetLastError()
            raise OSError(f"AssignProcessToJobObject failed with error {err}")
        logger.info("Assigned process to Job Object cage.")

    def terminate(self, exit_code: int = 1) -> None:
        """Terminate all processes in the Job Object."""
        if self._handle:
            kernel32 = ctypes.windll.kernel32
            kernel32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        """Close Job Object handle. Will trigger KILL_ON_JOB_CLOSE if processes remain."""
        if self._handle:
            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()


def create_isolated_temp_dir() -> Path:
    """Create an isolated, empty temporary working directory for the caged child."""
    base_tmp = Path(tempfile.gettempdir())
    cage_dir = base_tmp / f"friday_skill_cage_{uuid.uuid4().hex}"
    cage_dir.mkdir(parents=True, exist_ok=True)
    return cage_dir


def cleanup_isolated_temp_dir(path: Path) -> None:
    """Wipe the isolated temporary directory on exit."""
    if path.exists() and path.is_dir():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception as e:
            logger.warning("Failed to remove cage temp dir %s: %e", path, e)


def get_sanitized_cage_env(temp_dir: Path) -> Dict[str, str]:
    """Construct minimal child environment with only whitelisted variables."""
    sanitized: Dict[str, str] = {}
    for k, v in os.environ.items():
        if k.upper() in SAFE_CAGE_ENV_WHITELIST:
            sanitized[k] = v

    # Point PYTHONPATH to services/core/src and virtualenv site-packages
    core_src = Path(__file__).resolve().parent.parent.parent
    venv_site = Path(sys.prefix) / "Lib" / "site-packages"
    pythonpaths = [str(core_src)]
    if venv_site.exists():
        pythonpaths.append(str(venv_site))
    sanitized["PYTHONPATH"] = os.pathsep.join(pythonpaths)

    # Point TEMP and TMP to the isolated directory
    sanitized["TEMP"] = str(temp_dir)
    sanitized["TMP"] = str(temp_dir)
    return sanitized
