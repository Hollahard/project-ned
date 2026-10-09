"""Milestone 5 Empirical Challenger 2: Process Guardian, Soak Endurance & Security Harness.

Empirically challenges:
1. Win32 Job Object containment: verifies child processes are killed when parent process is killed (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 0x2000).
2. Win32 Job Object limit flags: queries kernel for 0x2000 and ActiveProcessLimit == 0.
3. Environment sanitization: empirically proves secret leakage without env_clear() and complete isolation with env_clear().
4. Post-execution process hygiene: verifies zero orphaned processes in tasklist.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

# Win32 Constants
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_empirical_job_object_kernel_kill_on_parent_force_terminate(tmp_path: Path):
    """Empirically test that when a parent process holding a Job Object with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is forcefully killed via taskkill /F,
    the Windows OS kernel immediately reaps all child worker processes.
    """
    assert kernel32 is not None

    # Python script for the sub-supervisor parent process
    sub_supervisor_code = r'''
import ctypes, os, subprocess, sys, time

kernel32 = ctypes.windll.kernel32

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9

# Create Job Object
h_job = kernel32.CreateJobObjectW(None, None)
if not h_job:
    sys.exit(1)

# Configure KILL_ON_JOB_CLOSE
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

info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

ret = kernel32.SetInformationJobObject(
    h_job,
    JobObjectExtendedLimitInformation,
    ctypes.byref(info),
    ctypes.sizeof(info),
)
if not ret:
    sys.exit(2)

# Spawn 3 child ping processes
child_pids = []
for _ in range(3):
    p = subprocess.Popen(["cmd.exe", "/c", "ping", "127.0.0.1", "-n", "40"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pids.append(p.pid)
    # Assign to Job Object
    h_proc = kernel32.OpenProcess(0x0100 | 0x0001 | 0x1000, False, p.pid)
    if h_proc:
        kernel32.AssignProcessToJobObject(h_job, h_proc)
        kernel32.CloseHandle(h_proc)

# Output child pids and flush stdout
print(f"READY:{','.join(map(str, child_pids))}", flush=True)

# Keep alive until killed externally
while True:
    time.sleep(1)
'''

    supervisor_script = tmp_path / "sub_supervisor.py"
    supervisor_script.write_text(sub_supervisor_code)

    # Spawn the sub-supervisor process
    sup_proc = subprocess.Popen(
        [sys.executable, str(supervisor_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Read the READY line
        ready_line = sup_proc.stdout.readline().strip()
        assert ready_line.startswith("READY:"), f"Unexpected supervisor output: {ready_line}"
        child_pids = [int(p) for p in ready_line.split(":", 1)[1].split(",")]
        assert len(child_pids) == 3

        # Verify all child processes are running
        for pid in child_pids:
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            assert h != 0, f"Child PID {pid} was not successfully started"
            kernel32.CloseHandle(h)

        # Forcefully terminate the sub-supervisor parent process (simulating hard crash)
        kill_res = subprocess.run(
            ["taskkill", "/F", "/PID", str(sup_proc.pid)],
            capture_output=True,
            text=True,
        )
        assert kill_res.returncode == 0, f"Failed to kill supervisor: {kill_res.stderr}"

        # Allow kernel a brief window to reap the Job Object
        time.sleep(0.5)

        # Confirm all 3 child worker processes were terminated by the Windows kernel
        for pid in child_pids:
            # Check if process is still active
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h != 0:
                exit_code = ctypes.c_ulong(0)
                kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
                kernel32.CloseHandle(h)
                # STILL_ACTIVE is 259
                assert exit_code.value != 259, f"Child worker PID {pid} survived parent kill!"

        # Query tasklist to verify no ping.exe remains
        res = subprocess.run(
            "tasklist | findstr /i ping.exe",
            shell=True,
            capture_output=True,
        )
        assert res.returncode == 1, "Orphaned ping.exe process detected in tasklist after parent death!"

    finally:
        sup_proc.kill()
        sup_proc.poll()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_empirical_job_object_limit_flags():
    """Verify Win32 Job Object limit flags:
    1. KILL_ON_JOB_CLOSE (0x2000) is enabled.
    2. ACTIVE_PROCESS (0x0008) is not enabled.
    3. ActiveProcessLimit == 0 (unrestricted child worker concurrency).
    """
    assert kernel32 is not None

    h_job = kernel32.CreateJobObjectW(None, None)
    assert h_job != 0

    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ret = kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        assert ret != 0

        query_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ret_len = ctypes.c_ulong(0)
        q_ret = kernel32.QueryInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(query_info),
            ctypes.sizeof(query_info),
            ctypes.byref(ret_len),
        )
        assert q_ret != 0

        flags = query_info.BasicLimitInformation.LimitFlags
        active_limit = query_info.BasicLimitInformation.ActiveProcessLimit

        assert (flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0, f"Flag 0x2000 missing in 0x{flags:08X}"
        assert (flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS) == 0, f"Flag 0x0008 incorrectly set in 0x{flags:08X}"
        assert active_limit == 0, f"ActiveProcessLimit should be 0, got {active_limit}"

    finally:
        kernel32.CloseHandle(h_job)


def test_empirical_environment_sanitization_proof():
    """Adversarial environment sanitization oracle:
    1. Poison parent environment with hostile API keys and credentials.
    2. Verify child process spawned with unsanitized environment leaks secrets.
    3. Verify child process spawned with sanitized whitelist + env_clear isolates 100% of secrets.
    """
    hostile_keys = {
        "ADVERSARIAL_API_KEY": "sk-live-stolen-credential-987654",
        "DATABASE_PASSWORD": "P@ssw0rd1234Secure!",
        "AWS_SECRET_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "GITHUB_TOKEN": "ghp_mocktokenforredteamtesting12345678",
    }

    # Poison environment
    for k, v in hostile_keys.items():
        os.environ[k] = v

    try:
        # Script to detect leaks
        detection_script = r'''
import os, sys
hostile = ['ADVERSARIAL_API_KEY', 'DATABASE_PASSWORD', 'AWS_SECRET_KEY', 'GITHUB_TOKEN']
found = [k for k in hostile if k in os.environ]
if found:
    print(f"LEAKED:{','.join(found)}")
    sys.exit(10)
else:
    print("CLEAN")
    sys.exit(0)
'''

        # Unsanitized run (default inheritance) -> MUST leak
        p_vuln = subprocess.run(
            [sys.executable, "-c", detection_script],
            capture_output=True,
            text=True,
        )
        assert p_vuln.returncode == 10
        assert "LEAKED" in p_vuln.stdout

        # Sanitized run: build whitelist environment
        whitelist_keys = [
            "PATH",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "COMSPEC",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE",
        ]
        sanitized_env = {k: os.environ[k] for k in whitelist_keys if k in os.environ}
        sanitized_env["PYTHONUNBUFFERED"] = "1"
        sanitized_env["FRIDAY_BEARER_TOKEN"] = "ephemeral-token"

        # Explicitly pass only sanitized_env (equivalent to env_clear + envs in Rust)
        p_clean = subprocess.run(
            [sys.executable, "-c", detection_script],
            env=sanitized_env,
            capture_output=True,
            text=True,
        )
        assert p_clean.returncode == 0
        assert "CLEAN" in p_clean.stdout

    finally:
        for k in hostile_keys:
            os.environ.pop(k, None)


def test_empirical_zero_orphaned_processes():
    """Verify zero orphaned ping.exe or worker processes currently exist in system."""
    res = subprocess.run(
        "tasklist | findstr /i ping.exe",
        shell=True,
        capture_output=True,
    )
    assert res.returncode == 1, "Orphaned ping.exe process detected in system tasklist!"
