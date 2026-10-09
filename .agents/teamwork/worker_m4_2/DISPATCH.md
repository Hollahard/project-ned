## 2026-10-09T16:47:24Z
You are the Worker for Milestone 4 Iteration 2: Child Process Environment Sanitization Fix (Requirement R4).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_2
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md (Strict workspace rules: always route test/build commands through temporary files cmd.exe /c "..." > log.txt 2>&1, inspect via view_file, and delete immediately).
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_2\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_explorer_1\handoff.md
6. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_explorer_2\handoff.md
7. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1\handoff.md

Write Ownership:
You have exclusive write ownership of:
- apps/desktop/src-tauri/src/processes.rs
- apps/desktop/src-tauri/tests/test_sanitized_env.rs

Objectives & Acceptance Criteria:
1. In apps/desktop/src-tauri/src/processes.rs:
   - In spawn_core (around line 315): add `.env_clear()` immediately before `.envs(&sanitized)`.
   - In spawn_tabby (around line 354): add `.env_clear()` immediately before `.envs(&sanitized)`.
2. In apps/desktop/src-tauri/tests/test_sanitized_env.rs:
   - Add a unit test `test_spawned_process_inherits_no_parent_secrets_with_env_clear` verifying that when parent secrets are set in the environment, a command constructed with `.env_clear().envs(&sanitized)` strips those secrets at OS execution time while preserving whitelisted keys (`PATH`, `CHILD_TOKEN`, etc.).
3. Verify baseline dirty file hashes in G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json match 100% and remain byte-identical.
4. Run full test verification following GEMINI.md routing:
   - cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1
   - pytest tests/security/ -v
   - pytest tests/soak/test_adversarial_cli_lifecycle.py -v
   - pytest tests/soak/test_soak_endurance.py -v -m soak
   - pytest services/core/tests/ -q
   - Confirm 0 compiler warnings, 0 test failures, and 0 orphaned processes.

Deliver your results in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_2\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
