# Original User Request

## 2026-10-07T15:09:01Z

Implement Phase 16: Continuous Soak and Long-Run Endurance Harness for Project Friday on the NVIDIA RTX 5090 workstation, adhering strictly to ADR-0002.

Working directory: G:\Project_Ned
Integrity mode: development

## Requirements

### R1. Fast Mocked Soak Test Suite (`tests/soak/test_soak_endurance.py`)
- Implement an automated endurance test suite marked with `@pytest.mark.soak` that completes in under 3 minutes using a mocked inference backend (`MockInferenceBackend`).
- Exercise 50 continuous turns incorporating:
  - Rapid mid-turn cancellations.
  - 4-tier memory churn (rapid insert, FTS5 scoped search, soft deletion).
  - SQLite scheduler concurrent job claims, timeouts, and duplicate execution suppression.
  - Depth-1 subagent delegations with budget reconciliation, proving monotonic permission containment and anti-recursion (grandchild delegation refusal).
  - Strict absence of `database is locked` errors, WAL growth exceeding 64 MB, or SQLite checkpoint stalls.

### R2. Standalone Long-Run Endurance Runner (`tests/soak/run_8hr_soak.py`)
- Implement a CLI runner supporting three duration modes:
  - `--mode smoke` (15 minutes fast qualification)
  - `--mode gate` (1 hour GPU qualification gate)
  - `--mode release` (8 hours full continuous soak run)
- Attribute VRAM specifically to the TabbyAPI PID via `nvidia-smi compute-apps` / NVML; verify post-unload residual memory returns to within 512 MB of baseline, and full process exit returns to pre-launch baseline.
- Sample Private Bytes, OS handle counts, thread counts, and loopback TCP connections for Core, TabbyAPI, and the supervisor; enforce tripwires:
  - Discard the first 15 minutes of warmup.
  - Abort if Private Bytes growth slope > 50 MB/hour.
  - Abort if OS handles climb > 50/hour or thread count monotonically ratchets.
  - Abort if GPU temperature exceeds 83°C.
- Periodically trigger scripted fault injections:
  - Gaming Mode evacuation (VRAM release and restore).
  - Mid-flight turn cancellation.
  - Core and MCP sidecar restarts inside the Windows Job Object.
- Stream telemetry dual-sink to `logs/traces/` and Langfuse Cloud, outputting `logs/soak_results.json` and generating `docs/benchmarks/soak_test_report.md`.

### R3. Rust Tauri Supervisor Endurance Contract (`apps/desktop/src-tauri`)
- Add integration tests to the Rust Tauri supervisor verifying:
  - Repeated session creation, telemetry polling, and preflight checks do not leak Windows OS handles or thread pools.
  - Supervisor window close cleanly terminates child processes (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) without setting active process limits that would break worker concurrency.

### R4. Security & Headless Approval Invariants
- Tests must execute headlessly and never simulate user clicks on Win32 system modal dialogs.
- Any operation with Risk >= 2 in the soak profile must be auto-denied and verified as a rejected capability.
- Capability tokens must strictly use the HMAC-SHA256 test stub bound to exact tool names and canonical arguments.
- Any test requiring real GPU weights must be marked with `@pytest.mark.gpu` to keep standard test runs offline and deterministic.

## Acceptance Criteria

### Automated Verification
- [ ] `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"` passes in under 3 minutes with zero warnings and no orphaned processes.
- [ ] `cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"` passes all supervisor handle leak and termination invariants.
- [ ] Smoke run `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke"` passes 15-minute qualification, validates baseline VRAM recovery, and writes `logs/soak_results.json`.
- [ ] All 198+ existing regression tests (`services/core/tests/`, `tests/security/`, `tests/e2e/`) continue passing cleanly without regressions.
