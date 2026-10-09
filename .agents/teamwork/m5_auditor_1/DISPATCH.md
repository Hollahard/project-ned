# DISPATCH — m5_auditor_1

## Task Assignment
Milestone 5: Comprehensive Final Forensic Integrity Audit.

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_auditor_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1\handoff.md`

## Forensic Integrity Audit Tasks
Conduct a comprehensive Forensic Integrity Audit across all project deliverables:
1. Scope Boundary Verification:
   - Verify that changes across all milestones (M1, M2, M3, M4) strictly conform to authorized boundaries in `PROJECT.md`.
   - Verify that baseline dirty files in `G:\Project_Ned` remain 100% byte-identical matching `preexisting-dirty-file-hashes.json`.
2. Authenticity & Anti-Cheating Verification:
   - Zero tolerance for hardcoded test results, facade implementations, mocked vector math, or bypassed security checks.
   - Inspect Tungstenite reconstruction and receipt files: verify authentic vendor archive reproduction.
   - Inspect vector DB and CPU embedder: verify authentic n-gram hashing and genuine cosine similarity.
   - Inspect approvals and processes: verify authentic Win32 HWND dialogs, HMAC tokens, Job Object flags, and `.env_clear()`.
   - Verify that the desktop UI truthfully reports backend unavailable.
3. Independent Empirical Multi-Suite Execution:
   - Run `Verify-Foundation.ps1 -NativeFixtures` (54 check groups).
   - Run `cargo test` in `hermes-native/services/owned-ws` (19 tests).
   - Run `cargo test` in `hermes-native/services/owned-http` (7 tests).
   - Run `pytest` in `hermes-native/services/owned-ws/tests/test_vendor_integrity.py` (8 tests).
   - Run `cargo test` in `apps/desktop/src-tauri` (36 tests).
   - Run `pytest services/core/tests/` (210 tests).
   - Run `pytest tests/security/` (37 tests).
   - Run `pytest tests/soak/test_adversarial_cli_lifecycle.py` (14 tests).
   - Run `pytest tests/soak/test_soak_endurance.py -m soak` (5 tests).
   - Confirm zero compiler warnings, zero test failures, zero orphaned processes.

## Output
Deliver your final audit verdict (`CLEAN` or `INTEGRITY VIOLATION`) with full evidence chains in:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_auditor_1\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.

## 2026-10-09T17:31:54Z

**Context**: Milestone 5 Foundation Verification execution in Forensic Audit Phase 3.
**Content**: `hermes-native/scripts/Verify-Foundation.ps1` declares mandatory parameters `[Parameter(Mandatory = $true)][string]$UpstreamRoot` and `[Parameter(Mandatory = $true)][string]$TabbySource`, and requires the active Python venv (`$env:VIRTUAL_ENV`). Invocations omitting these parameters block indefinitely waiting for user stdin in PowerShell. Your background task `task-152` is stalled waiting for input.
**Action**: Kill your background task `5559fa30-045f-43a0-b0b9-7df2b0e849af/task-152` using `manage_task(Action="kill", TaskId="5559fa30-045f-43a0-b0b9-7df2b0e849af/task-152")`. Then invoke the verified foundation command via:
`cmd.exe /c "pwsh -NoProfile -Command "". .\.venv\Scripts\Activate.ps1; & hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -NativeFixtures"" > verify_foundation.log 2>&1"`
Inspect `verify_foundation.log`, confirm all 54 check groups pass, delete the log, and proceed with the remaining verification suites in your audit checklist.
