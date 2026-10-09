# DISPATCH — worker_m5_1

## Task Assignment
Milestone 5: Final Multi-Suite Acceptance Qualification (Requirements R1, R2, R3, R4).

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Strict workspace rules: always route test commands through temporary files `cmd.exe /c "..." > log.txt 2>&1`, inspect via `view_file`, and delete immediately).
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md`

## Qualification Tasks
Execute and verify the full acceptance test suite matrix following GEMINI.md routing:
1. Foundation Verification (54 groups, including 4 vendor gates):
   `cmd.exe /c "powershell -ExecutionPolicy Bypass -File hermes-native/scripts/Verify-Foundation.ps1 -NativeFixtures > verify_found.log 2>&1"`
2. Owned WebSocket Test Suite (19 tests):
   `cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml > owned_ws.log 2>&1"`
3. Owned HTTP Test Suite (7 tests):
   `cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-http/Cargo.toml > owned_http.log 2>&1"`
4. Python Vendor Integrity Suite (8 tests):
   `cmd.exe /c ".\.venv\Scripts\pytest.exe hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > vendor_integ.log 2>&1"`
5. Desktop Supervisor Suite (36 tests):
   `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > desktop_cargo.log 2>&1"`
6. Python Core Test Suite (210 tests):
   `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -q > core_pytest.log 2>&1"`
7. Security Test Suite (37 tests):
   `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > sec_pytest.log 2>&1"`
8. Adversarial CLI Lifecycle Suite (14 tests):
   `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > adv_pytest.log 2>&1"`
9. Soak Endurance Suite (5 tests):
   `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_pytest.log 2>&1"`
10. Baseline Dirty File Hash Verification:
    Verify that all 4 files in `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json` remain 100% byte-identical.
11. Desktop UI Backend-Unavailable Reporting:
    Verify that the desktop UI truthfully reports backend unavailable until gateway qualification.
12. Orphaned Process Check:
    Verify zero orphaned `ping.exe`, `pytest.exe`, or `python.exe` processes via tasklist.

## Output
Deliver comprehensive qualification results in:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.
