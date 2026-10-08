"""Windows 10+ atomic Job Object launch with an explicit inherited-handle list.

This proof-local launcher will be consolidated into the Rust resource host.
It never searches for a PID or port to terminate, and captures no log files.
"""

import ctypes as c
import os
import re
import subprocess
import threading
import time
from ctypes import wintypes as w
from pathlib import Path

from .readiness import ReadinessError, ReadinessParser

if os.name != "nt":
    raise ImportError("Windows process ownership requires Windows")

k32 = c.WinDLL("kernel32", use_last_error=True)
SIZE_T = c.c_size_t
LPVOID = c.c_void_p


class SecurityAttributes(c.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", LPVOID), ("inherit", w.BOOL)]


class StartupInfo(c.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("x_size", w.DWORD),
        ("y_size", w.DWORD),
        ("x_chars", w.DWORD),
        ("y_chars", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved2", LPVOID),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class StartupInfoEx(c.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", LPVOID)]


class ProcessInformation(c.Structure):
    _fields_ = [
        ("process", w.HANDLE),
        ("thread", w.HANDLE),
        ("pid", w.DWORD),
        ("tid", w.DWORD),
    ]


class BasicLimit(c.Structure):
    _fields_ = [
        ("process_time", c.c_longlong),
        ("job_time", c.c_longlong),
        ("flags", w.DWORD),
        ("minimum_working_set", SIZE_T),
        ("maximum_working_set", SIZE_T),
        ("active_process_limit", w.DWORD),
        ("affinity", SIZE_T),
        ("priority_class", w.DWORD),
        ("scheduling_class", w.DWORD),
    ]


class ExtendedLimit(c.Structure):
    _fields_ = [
        ("basic", BasicLimit),
        ("io", c.c_ulonglong * 6),
        ("process_memory", SIZE_T),
        ("job_memory", SIZE_T),
        ("peak_process_memory", SIZE_T),
        ("peak_job_memory", SIZE_T),
    ]


class Accounting(c.Structure):
    _fields_ = [
        ("total_user", c.c_longlong),
        ("total_kernel", c.c_longlong),
        ("period_user", c.c_longlong),
        ("period_kernel", c.c_longlong),
        ("page_faults", w.DWORD),
        ("total_processes", w.DWORD),
        ("active_processes", w.DWORD),
        ("terminated_processes", w.DWORD),
    ]


def _bind(name, args, result=w.BOOL):
    fn = getattr(k32, name)
    fn.argtypes, fn.restype = args, result
    return fn


CloseHandle = _bind("CloseHandle", [w.HANDLE])
CreateJobObject = _bind("CreateJobObjectW", [LPVOID, w.LPCWSTR], w.HANDLE)
SetInformationJobObject = _bind(
    "SetInformationJobObject", [w.HANDLE, c.c_int, LPVOID, w.DWORD]
)
QueryInformationJobObject = _bind(
    "QueryInformationJobObject", [w.HANDLE, c.c_int, LPVOID, w.DWORD, LPVOID]
)
TerminateJobObject = _bind("TerminateJobObject", [w.HANDLE, w.UINT])
CreatePipe = _bind("CreatePipe", [LPVOID, LPVOID, LPVOID, w.DWORD])
SetHandleInformation = _bind("SetHandleInformation", [w.HANDLE, w.DWORD, w.DWORD])
CreateFile = _bind(
    "CreateFileW",
    [w.LPCWSTR, w.DWORD, w.DWORD, LPVOID, w.DWORD, w.DWORD, w.HANDLE],
    w.HANDLE,
)
InitializeAttributes = _bind(
    "InitializeProcThreadAttributeList", [LPVOID, w.DWORD, w.DWORD, LPVOID]
)
UpdateAttribute = _bind(
    "UpdateProcThreadAttribute",
    [LPVOID, w.DWORD, SIZE_T, LPVOID, SIZE_T, LPVOID, LPVOID],
)
DeleteAttributes = _bind("DeleteProcThreadAttributeList", [LPVOID], None)
CreateProcess = _bind(
    "CreateProcessW",
    [
        w.LPCWSTR,
        w.LPWSTR,
        LPVOID,
        LPVOID,
        w.BOOL,
        w.DWORD,
        LPVOID,
        w.LPCWSTR,
        LPVOID,
        LPVOID,
    ],
)
ReadFile = _bind("ReadFile", [w.HANDLE, LPVOID, w.DWORD, LPVOID, LPVOID])
WaitForSingleObject = _bind("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD)
GetExitCodeProcess = _bind("GetExitCodeProcess", [w.HANDLE, LPVOID])
OpenProcess = _bind("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
IsProcessInJob = _bind("IsProcessInJob", [w.HANDLE, w.HANDLE, LPVOID])


def _check(ok):
    if not ok:
        raise c.WinError(c.get_last_error())
    return ok


def environment_block(values: dict[str, str]):
    seen = set()
    entries = []
    for key, value in values.items():
        if (
            not re.fullmatch(r"[A-Za-z0-9_]+", key)
            or key.upper() in seen
            or "\0" in value
        ):
            raise ValueError("Invalid explicit child environment")
        seen.add(key.upper())
        entries.append((key.upper(), f"{key}={value}"))
    return c.create_unicode_buffer(
        "\0".join(value for _, value in sorted(entries)) + "\0"
    )


class OwnedProcess:
    """One launch, one non-inheritable job; close permanently destroys ownership."""

    def __init__(
        self,
        executable: Path,
        arguments: list[str],
        cwd: Path,
        environment: dict[str, str],
    ):
        if not executable.is_absolute() or not cwd.is_absolute():
            raise ValueError("Absolute executable and working directory required")
        if (
            not executable.is_file()
            or not cwd.is_dir()
            or executable.suffix.lower() != ".exe"
        ):
            raise ValueError("Existing executable and directory required")
        if any("\0" in item for item in [str(executable), str(cwd), *arguments]):
            raise ValueError("NUL in process inputs")
        command = subprocess.list2cmdline([str(executable), *arguments])
        if len(command.encode("utf-16-le")) // 2 + 1 > 32767:
            raise ValueError("Windows command line exceeds its bound")
        env = environment_block(environment)
        self.readiness = ReadinessParser()
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self._read_errors = []
        self._threads = []
        self._job = self._process = None
        self._lock = threading.RLock()
        self._closed = False
        handles = []
        attributes = None
        attributes_initialized = False
        try:
            self._job = _check(CreateJobObject(None, None))
            limits = ExtendedLimit()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _check(
                SetInformationJobObject(self._job, 9, c.byref(limits), c.sizeof(limits))
            )
            sa = SecurityAttributes(c.sizeof(SecurityAttributes), None, True)
            reads, writes = [], []
            for _ in range(2):
                reader, writer = w.HANDLE(), w.HANDLE()
                _check(CreatePipe(c.byref(reader), c.byref(writer), c.byref(sa), 0))
                handles.extend([reader.value, writer.value])
                _check(SetHandleInformation(reader, 1, 0))
                reads.append(reader.value)
                writes.append(writer.value)
            stdin = CreateFile("NUL", 0x80000000, 3, c.byref(sa), 3, 0x80, None)
            if stdin == w.HANDLE(-1).value:
                raise c.WinError(c.get_last_error())
            handles.append(stdin)
            size = SIZE_T()
            InitializeAttributes(None, 2, 0, c.byref(size))
            if not size.value:
                raise c.WinError(c.get_last_error())
            attributes = c.create_string_buffer(size.value)
            _check(InitializeAttributes(attributes, 2, 0, c.byref(size)))
            attributes_initialized = True
            inherited = (w.HANDLE * 3)(stdin, *writes)
            jobs = (w.HANDLE * 1)(self._job)
            _check(
                UpdateAttribute(
                    attributes, 0, 0x20002, inherited, c.sizeof(inherited), None, None
                )
            )
            _check(
                UpdateAttribute(
                    attributes, 0, 0x2000D, jobs, c.sizeof(jobs), None, None
                )
            )
            startup = StartupInfoEx()
            startup.startup.cb = c.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = (
                stdin,
                *writes,
            )
            startup.attributes = c.cast(attributes, LPVOID)
            info = ProcessInformation()
            _check(
                CreateProcess(
                    str(executable),
                    c.create_unicode_buffer(command),
                    None,
                    None,
                    True,
                    0x08000000 | 0x00000400 | 0x00080000,
                    env,
                    str(cwd),
                    c.byref(startup),
                    c.byref(info),
                )
            )
            self._process, self.pid = info.process, info.pid
            CloseHandle(info.thread)
            for value in [stdin, *writes]:
                CloseHandle(value)
                handles.remove(value)
            for index, reader in enumerate(reads):
                thread = threading.Thread(
                    target=self._drain, args=(reader, index == 0), daemon=True
                )
                thread.start()
                self._threads.append(thread)
                handles.remove(reader)
        except BaseException:
            # Release parent copies of writer handles before joining readers;
            # otherwise a partial constructor failure can prevent pipe EOF.
            for handle in handles:
                CloseHandle(handle)
            handles.clear()
            self.close()
            raise
        finally:
            if attributes_initialized:
                DeleteAttributes(attributes)
            for handle in handles:
                CloseHandle(handle)

    def _drain(self, handle, stdout):
        buffer = c.create_string_buffer(4096)
        count = w.DWORD()
        try:
            while ReadFile(handle, buffer, len(buffer), c.byref(count), None):
                if not count.value:
                    break
                if stdout:
                    self.stdout_bytes += count.value
                    self.readiness.feed(buffer.raw[: count.value])
                else:
                    self.stderr_bytes += count.value
        finally:
            error = c.get_last_error()
            if error not in (0, 109, 232):  # normal pipe EOF
                self._read_errors.append(error)
            if stdout:
                self.readiness.eof()
            CloseHandle(handle)

    def poll(self):
        with self._lock:
            if self._process is None:
                raise RuntimeError("Owned process handle is closed")
            result = WaitForSingleObject(self._process, 0)
            if result == 258:
                return None
            if result != 0:
                raise c.WinError(c.get_last_error())
            code = w.DWORD()
            _check(GetExitCodeProcess(self._process, c.byref(code)))
            return code.value

    def active_count(self):
        with self._lock:
            if self._job is None:
                raise RuntimeError("Owned job handle is closed")
            accounting = Accounting()
            _check(
                QueryInformationJobObject(
                    self._job, 1, c.byref(accounting), c.sizeof(accounting), None
                )
            )
            return accounting.active_processes

    def contains_observed_pid(self, pid: int) -> bool:
        """Read-only membership snapshot, never adoption or termination by PID.

        Windows virtual-environment redirectors can launch a second Python
        process. A HTTP server's PID need not equal the created root PID.
        """
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            return False
        with self._lock:
            if self._job is None:
                raise RuntimeError("Owned job handle is closed")
            handle = OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only
            if not handle:
                return False
            try:
                member = w.BOOL()
                _check(IsProcessInJob(handle, self._job, c.byref(member)))
                return bool(member.value)
            finally:
                CloseHandle(handle)

    def wait_ready(self, timeout: float = 30.0) -> int:
        if not 0 < timeout <= 120:
            raise ValueError("Readiness deadline must be within 120 seconds")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            port = self.readiness.port()
            if self.poll() is not None:
                raise ReadinessError("Owned child exited before readiness verification")
            if self._read_errors:
                raise ReadinessError("Owned child output capture failed")
            if port is not None:
                return port
            self.readiness.changed.wait(min(0.02, max(0, deadline - time.monotonic())))
        raise ReadinessError("Owned child readiness deadline expired")

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            failure = None
            if self._job:
                try:
                    if not TerminateJobObject(self._job, 79):
                        failure = "Owned job termination failed"
                    deadline = time.monotonic() + 5
                    while self.active_count() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if self.active_count():
                        failure = (
                            "Owned descendants did not exit within the cleanup bound"
                        )
                except OSError:
                    failure = "Owned job exit could not be verified"
                finally:
                    CloseHandle(self._job)
                    self._job = None
            if self._process:
                if WaitForSingleObject(self._process, 5000) != 0:
                    failure = "Owned process did not exit within the cleanup bound"
                CloseHandle(self._process)
                self._process = None
            for thread in self._threads:
                thread.join(timeout=2)
                if thread.is_alive():
                    failure = "Owned output capture did not reach EOF"
            if failure:
                raise RuntimeError(failure)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
