# DISPATCH — worker_m4_1

## Task Assignment
Milestone 4: Process Guardian & Windows Job Object Security Containment (Requirement R4).

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Strict workspace rules: always route test/build commands through temporary files `cmd.exe /c "..." > log.txt 2>&1`, inspect via `view_file`, and delete immediately).
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\handoff.md`

## Write Ownership
You have exclusive write ownership of:
- `apps/desktop/src-tauri/src/proxy.rs`
- `apps/desktop/src-tauri/src/approvals.rs`
- `apps/desktop/src-tauri/src/processes.rs`

## Objectives & Deliverables
1. **Loopback Proxy Fix (`apps/desktop/src-tauri/src/proxy.rs`)**:
   - Inspect line 132 `reqwest::Client::builder()`.
   - Add `.no_proxy()` to client builder so requests to `http://127.0.0.1:<port>` are never intercepted by Windows system/corporate proxies (preventing HTTP 400 "Direct IP access is not allowed").
2. **Win32 HWND Binding (`apps/desktop/src-tauri/src/approvals.rs`)**:
   - Verify modal approval dialogs (`MessageBoxW`) and HMAC-SHA256 capability tokens are bound to the caller's main window Win32 `HWND` rather than detached `null_mut()`.
   - Ensure `canonicalize_json_value` sorts keys deterministically (`sort_keys=True` parity with Python).
   - Verify single-use token consumption and 120s TTL.
3. **Windows Job Object Containment & Concurrency (`apps/desktop/src-tauri/src/processes.rs`)**:
   - Verify `CreateJobObjectW` sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` and denies breakaway.
   - Verify child worker concurrency is unrestricted: `ActiveProcessLimit == 0` (omits `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`).
   - Verify child environment sanitization: `build_sanitized_env` whitelists only system variables (`PATH`, `TEMP`, `SYSTEMROOT`, etc.) and strips all parent secrets.
4. **Baseline Dirty File Preservation**:
   - Inspect `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`.
   - Verify that all 4 files in `G:\Project_Ned` match the expected hashes 100% and are preserved byte-identically.
5. **Execution & Verification**:
   - Follow GEMINI.md routing strictly:
     * Run `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml`
     * Run `pytest tests/security/ -v`
     * Run `pytest tests/soak/test_adversarial_cli_lifecycle.py -v`
   - Ensure zero compiler warnings, zero test failures, zero orphaned processes.

## Output
Write your full report to:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1\handoff.md`

## 2026-10-09T16:00:57Z
You are the Worker for Milestone 4: Process Guardian & Windows Job Object Security Containment (Requirement R4).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md (Strict workspace rules: always route test/build commands through temporary files cmd.exe /c "..." > log.txt 2>&1, inspect via view_file, and delete immediately).
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\handoff.md

Write Ownership:
You have exclusive write ownership of:
- apps/desktop/src-tauri/src/proxy.rs
- apps/desktop/src-tauri/src/approvals.rs
- apps/desktop/src-tauri/src/processes.rs

Objectives & Acceptance Criteria:
1. Fix loopback proxy in apps/desktop/src-tauri/src/proxy.rs:
   - In reqwest::Client::builder() (around line 132), add `.no_proxy()` to ensure loopback requests to 127.0.0.1 bypass system proxies, fixing HTTP 400 "Direct IP access is not allowed".
2. Wire Win32 HWND binding into apps/desktop/src-tauri/src/approvals.rs:
   - Ensure native dialogs (MessageBoxW) and capability tokens bind to the caller Win32 HWND rather than null_mut().
   - Verify deterministic JSON canonicalization (sort_keys=True parity), 120s TTL, and single-use consumption.
3. Verify Process Guardian & Job Object in apps/desktop/src-tauri/src/processes.rs:
   - JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) and zero breakaway.
   - ActiveProcessLimit == 0 (unrestricted child worker concurrency).
   - build_sanitized_env whitelisting PATH, TEMP, SYSTEMROOT etc. and stripping parent secrets.
4. Verify baseline dirty file hashes in G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json match 100% and remain byte-identical.
5. Verification:
   - Run Rust tests following GEMINI.md:
     cmd.exe /c "cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.log 2>&1"
     Inspect log, confirm all tests pass, delete log.
   - Run security tests:
     cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > pytest_sec.log 2>&1"
     Inspect log, confirm all pass, delete log.
   - Run adversarial lifecycle tests:
     cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > pytest_soak.log 2>&1"
     Inspect log, confirm all pass, delete log.

Deliver your results in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
