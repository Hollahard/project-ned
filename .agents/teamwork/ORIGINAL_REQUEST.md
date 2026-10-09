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


## 2026-10-07T18:26:31Z

Server restarted and context was truncated. Please report the current status of Phase 16 Victory Audit. Specifically:
1. Did the independent Victory Auditor (conversation d911e8ab-11f1-4bbe-a39b-23b8866380b5) complete its Phase C independent test execution?
2. What is the final verdict — VICTORY CONFIRMED or VICTORY REJECTED?
3. If the auditor is no longer reachable, please independently verify by running the full test suite:
   - `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_verify.txt 2>&1"` in G:\Project_Ned
   - `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -v > regression_verify.txt 2>&1"` in G:\Project_Ned
   Inspect and delete log files, then report pass/fail counts.
Report back with the final verdict so Phase 16 can be formally sealed.


## 2026-10-09T13:42:19Z

Resume Project Ned native desktop integration from checkpoint commit 2afa8ea on branch codex/hermes-native-foundation. Promote unfinished socket actor candidates, fix client TypeScript typechecking, verify owned WebSocket transports, and implement the local vector database / memory foundation with strict Windows process isolation.

Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned
Integrity mode: development

## Requirements

### R1. Candidate Socket Promotion & Client Typecheck Resolution
- Promote and integrate preserved candidates from docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip and manifest socket-candidates-20261008.json.
- Fix the TypeScript strict typecheck error TS2367 in hermes-native/apps/desktop-ui/src/native-gateway-socket.ts (state comparison between narrowed CONNECTING and CLOSING after async operation).
- Ensure all 28 vendored Tungstenite 0.30.0 output files reconstruct cleanly with verified hashes and no silent newline mutations.
- Enforce parser progress safety: observations after fatal protocol errors must never produce valid application state; peer close must not self-certify actor retirement; preceding message order must be preserved ahead of terminal frames.

### R2. Owned WebSocket & Transport Foundation Verification
- Run and pass all 19 owned-ws tests, 7 owned-http tests, 8 parser progress tests, and 8 Python vendor-tamper tests against frozen vendor sources.
- Expand and pass hermes-native/scripts/Verify-Foundation.ps1 to incorporate the new transport gates and receipt evidence without regressing existing 52 groups / 489 component tests.
- Keep the desktop UI truthfully reporting backend unavailable until live gateway handshake and startup contracts are fully qualified.

### R3. Core Memory & Vector Database Foundation
- Design and implement durable local memory schema with sqlite-vec / SQLite storage.
- Establish embedding strategies, retrieval, eviction, and reconciliation boundaries without unmanaged external network calls or cloud dependencies.
- Ensure async database connections and thread pools cleanly teardown to prevent hanging pytest subshells or orphaned worker threads on Windows.

### R4. Process Guardian & Windows Job Object Security Containment
- All child processes (Core and TabbyAPI / inference sidecars) must execute strictly inside Windows Job Objects with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE enabled.
- Sanitize child process environments by whitelisting only explicit variables (PATH, TEMP, SYSTEMROOT) and stripping parent secrets.
- Isolate credentials: tokens must be one-shot HMAC-SHA256, bound to Win32 window handles (HWND), with zero credential leakage to WebView2 URLs or renderer events.

## Acceptance Criteria

### Transport & Client Readiness
- [ ] TypeScript strict check passes cleanly with zero errors on hermes-native/apps/desktop-ui/src/native-gateway-socket.ts.
- [ ] All 19 owned-ws tests, 7 owned-http tests, and 8 input_progress tests pass cleanly.
- [ ] Python vendor integrity suite (test_vendor_integrity.py) passes 8/8 tests.
- [ ] Foundation verification script (Verify-Foundation.ps1) completes with 100% passing status and records complete verification evidence.

### Memory & Vector Storage
- [ ] SQLite / sqlite-vec memory database initializes cleanly in isolated test fixtures.
- [ ] Vector retrieval, deletion, and reconciliation pass programmatic unit and integration tests.
- [ ] All async database fixtures explicitly await db_manager.close() during teardown with zero worker thread hangs.

### Security & Invariant Verification
- [ ] Process guardian terminates all child processes upon parent exit without orphan leaks.
- [ ] Zero bearer tokens or credentials appear in WebView2 console logs, URLs, or client-side storage.
- [ ] Baseline dirty files remain strictly byte-identical to preexisting-dirty-file-hashes.json.
