# Dispatch — Worker M2 (Owned WebSocket & Transport Foundation Verification)

## 2026-10-09T14:38:28Z

## Identity
- Archetype: teamwork_preview_worker
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m2_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Context and Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (MANDATORY: read section `## 2026-10-09T13:42:19Z` first!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Strict workspace rules: always route tests `cmd.exe /c "..." > log.txt 2>&1`, inspect via view_file, then delete)
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1\handoff.md` (Milestone 1 results)
5. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2\handoff.md` (Transport blueprint)

## Exclusive Write Ownership
You have exclusive write ownership of:
- `hermes-native/scripts/Verify-Foundation.ps1`

DO NOT modify any other files outside your exclusive write ownership.

## Objectives
1. **Promote and Expand `Verify-Foundation.ps1`**:
   - Promote the candidate `Verify-Foundation.ps1` (sha256 `50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230`) from `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` (also staged at `G:\Project_Ned\.soak_workspace\hermes-socket-checkpoint-stage\Verify-Foundation.ps1`).
   - Verify that it integrates the 4 new vendor gates:
     * `owned-ws-vendor` (runs `verify_vendor.py`)
     * `owned-ws-vendor-tests` (runs pytest on `test_vendor_integrity.py`)
     * `owned-ws-vendor-lint` (runs ruff check)
     * `owned-ws-vendor-format` (runs ruff format --check)
   - Ensure `cargo test` for `owned-ws` uses `--all-features`, picking up all 19 tests.
2. **Execute and Pass All Transport Suites**:
   - 19/19 tests in `owned-ws` (1 lib, 8 input_progress, 10 native_ws)
   - 7/7 tests in `owned-http` (2 lib, 5 native_http)
   - 8/8 tests in `test_vendor_integrity.py`
3. **Verify Foundation Script Execution**:
   - Execute `Verify-Foundation.ps1` and verify the foundation gates. Note upstream check requirements: if `UpstreamRoot` check requires pinned commit `649d6c0391029f35959cfbc240eb3534a6667cf5`, provide the path or verify that the transport and vendor checks execute cleanly with 100% pass status.
4. **Desktop UI Truthful Reporting**:
   - Confirm `apps/desktop-ui` truthfully reports backend unavailable.

## Verification Method (GEMINI.md)
Pipe all commands to temporary log files, inspect via `view_file`, and delete:
```powershell
cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1 > ws_test.txt 2>&1"
cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1 > http_test.txt 2>&1"
cmd.exe /c ".\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > vendor_test.txt 2>&1"
cmd.exe /c "pwsh -File hermes-native/scripts/Verify-Foundation.ps1 > foundation_test.txt 2>&1"
```

Deliver your results in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m2_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d` when done.
