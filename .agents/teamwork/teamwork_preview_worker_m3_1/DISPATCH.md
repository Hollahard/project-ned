## 2026-10-07T17:17:33Z
You are the Worker for Milestone 3: Standalone Long-Run Endurance Runner.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m3_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md (Authoritative ADR-0002)
4. G:\Project_Ned\GEMINI.md (Strict workspace rules: cmd.exe /c test output piping, zero orphaned processes)
5. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_1\handoff.md (CLI & Win32JobSupervisor blueprints)
6. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\handoff.md (Telemetry, Win32 ctypes fallback [no psutil in .venv], NVML Tabby VRAM attribution, OLS slope, thread ratchet, 83°C thermal monitor, disabling tracemalloc, dual-sink streaming)
7. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\handoff.md (Fault injectors: Gaming mode < 2.0s, mid-turn cancel, Job Object restart; VRAM recovery oracle; Artifact schemas for soak_results.json and soak_test_report.md)
8. G:\Project_Ned\tests\soak\run_8hr_soak.py (Existing runner to refactor/replace)

Write Ownership:
You have EXCLUSIVE write ownership of:
- G:\Project_Ned\tests\soak\run_8hr_soak.py
And test-generated outputs:
- G:\Project_Ned\logs\soak_results.json
- G:\Project_Ned\docs\benchmarks\soak_test_report.md
DO NOT touch other files unless strictly required.

Objective:
Implement the complete, production-grade standalone long-run endurance runner in `tests/soak/run_8hr_soak.py`:
1. CLI:
   - Accept `--mode smoke` (15m), `--mode gate` (1h), `--mode release` (8h), and `--mode custom` (plus aliases 15m, 1h, 8h).
   - Accept `--duration-minutes`, `--warmup-minutes` (scaled for smoke e.g. 3m, or 15m for gate/release), `--sample-interval-seconds`, `--output-dir`, `--report-dir`, `--workspace`, `--headless`, `--target-mode` (`mock` [default], `spawn`, `attach`), `--core-port`, `--tabby-port`, `--core-pid`, `--tabby-pid`, `--supervisor-pid`, `--gpu`, `--fail-fast`, `--langfuse`.
2. Windows Job Object Supervision & Lifecycle:
   - `Win32JobSupervisor` using native ctypes: creates Job Object, sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` WITHOUT `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`. Assigns children via `AssignProcessToJobObject`. Queries active count via `JobObjectBasicAccountingInformation`. Terminates all via `TerminateJobObject`.
   - `GracefulShutdownCoordinator`: handles SIGINT/SIGTERM, triggers cooperative turn cancellation, flushes/checkpoints SQLite databases (`PRAGMA wal_checkpoint(TRUNCATE)`), closes handles, and ensures 0 orphaned processes remain.
3. Telemetry & Metrics:
   - Zero-dependency Win32 `ctypes` (`kernel32`, `psapi`, `iphlpapi`) fallback (note: `psutil` is not installed in `.venv`).
   - Private Bytes (`PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`), Handle Count (`GetProcessHandleCount`), Thread Count (`CreateToolhelp32Snapshot`), and loopback TCP connections.
   - NVML / `nvidia-smi` Tabby VRAM attribution cascade (`nvmlDeviceGetComputeRunningProcesses` / `nvidia-smi compute-apps` / device delta / mock profile) and GPU temperature monitor.
   - Guarantee `tracemalloc.is_tracing() is False` throughout.
4. Mathematical Tripwires:
   - Discard warmup samples (`elapsed_seconds >= warmup_seconds`).
   - OLS linear regression slope: Private Bytes slope > 50 MB/hr abort (with net drift > 10 MB).
   - OLS linear regression slope: Handle count slope > 50/hr abort (with net drift > 10).
   - Sliding-window thread ratchet detector across quartiles.
   - GPU temperature >= 83°C abort.
   - SQLite WAL > 64 MB abort.
5. Scripted Fault Injections & Oracles:
   - Gaming Mode evacuation (< 2.0s deadline via `time.perf_counter()`, in-flight abort, rejection while active, restore).
   - Mid-turn cancel (audit active tasks, verify 0 leaked tasks, empty active cancels, verify loop recovery).
   - Job Object sidecar restart (child process termination inside Job Object, verify ActiveProcesses drops to 0, restart inside Job Object, 0 orphans).
   - VRAM Recovery Oracle (track pre-launch baseline, post-start baseline, residual check <= 512 MB, monotonic drift check, exit return to baseline).
6. Dual-sink Telemetry & Reporting:
   - Stream events to `logs/traces/soak_<timestamp>.jsonl`.
   - Optional Langfuse Cloud mirroring (graceful fallback if unconfigured).
   - Generate `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md` (featuring NVIDIA GeForce RTX 5090 Blackwell hardware environment, metrics table, fault matrix, and ASCII sparklines).

Verification Step:
Execute following GEMINI.md:
1. `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --help > help_run.txt 2>&1"`
   Inspect `help_run.txt`, verify `--mode smoke` is recognized, then delete `help_run.txt`.
2. `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode custom --duration-minutes 0.5 --warmup-minutes 0.1 --sample-interval-seconds 2 > short_run.txt 2>&1"`
   Inspect `short_run.txt`, verify execution runs cleanly, tripwires pass, and delete `short_run.txt`.
3. Check generated artifacts: `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md`.
4. Verify 0 orphaned processes: `cmd.exe /c "tasklist | findstr /i ping.exe"` returns code 1.
