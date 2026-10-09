# BRIEFING — 2026-10-09T16:45:00Z

## Mission
Repo-Wide Process Spawn Audit to determine if any process spawning locations beyond apps/desktop/src-tauri/src/processes.rs intend to sanitize environment variables or omit env_clear()/env sanitization.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigator, synthesizer
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_explorer_2
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Milestone: Milestone 4 Iteration 2 (Repo-Wide Process Spawn Audit)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Audit child process creation across apps/desktop/src-tauri/, hermes-native/, services/core/
- Determine whether any other process spawns intend to be sanitized but omit env_clear()
- Inspect hermes-native/services/resource-host/ and services/core/src/friday/skills/cage.py
- Deliver findings on whether the fix should be confined exclusively to apps/desktop/src-tauri/src/processes.rs or if other files need adjustment

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: 2026-10-09T16:45:00Z

## Investigation State
- **Explored paths**:
  - `apps/desktop/src-tauri/src/processes.rs`, `runtime.rs`, `commands.rs`, `lib.rs`, `approvals.rs`, `proxy.rs`, `tests/*`
  - `hermes-native/services/resource-host/` (`src/windows.rs`, `src/capture.rs`, `src/bin/worker_fixture.rs`, `tests/owned_workers.rs`, `tests/captured_workers.rs`)
  - `hermes-native/services/backend-host/` (`windows_process.py`)
  - `hermes-native/services/terminal-host/` (`src/lib.rs`, `src/bin/terminal-fixture.rs`, `tests/conpty.rs`)
  - `hermes-native/services/control-host/` (`tests/owned_control.rs`)
  - `hermes-native/services/catalog-host/` (`tests/owned_catalog.rs`, `src/state.rs`, `src/lib.rs`)
  - `hermes-native/services/owned-ws/`, `owned-http/` (`tests/fixtures/server.rs`)
  - `services/core/src/friday/skills/cage.py`, `supervisor.py`
  - `services/core/src/friday/tools/terminal_exec.py`, `native_read.py`
  - `services/core/src/friday/security/powershell.py`
  - `services/core/src/friday/storage/checkpoints.py`
  - `tests/soak/test_adversarial_cli_lifecycle.py`, `test_challenger_m3.py`, `run_8hr_soak.py`
- **Key findings**:
  - `apps/desktop/src-tauri/src/processes.rs` (`spawn_core` and `spawn_tabby`) is the ONLY production location where `Command::new` builds a sanitized environment but omits `.env_clear()`.
  - In `hermes-native`, production services (`resource-host`, `backend-host`, `terminal-host`) use direct Win32 `CreateProcessW` with explicit Unicode environment blocks (`CREATE_UNICODE_ENVIRONMENT`), natively bypassing `Command` and guaranteeing zero parent environment inheritance.
  - Test fixtures in `hermes-native` (`control-host/tests/owned_control.rs:249` and `terminal-host/tests/conpty.rs:91`) already explicitly call `.env_clear()`.
  - In `services/core`, `skills/supervisor.py` and `tools/terminal_exec.py` use Python's `subprocess.Popen(..., env=env)` and `asyncio.create_subprocess_exec(..., env=env)`. In Python, specifying `env` completely replaces the child environment (passes it directly to `CreateProcessW`) rather than merging with `os.environ`.
  - Therefore, the fix is EXCLUSIVELY confined to `apps/desktop/src-tauri/src/processes.rs`.
- **Unexplored areas**: None. Audit is exhaustive across all codebases in the repository.

## Key Decisions Made
- Audit confirmed zero additional files require modification.
- Documenting complete evidence chain and findings in `handoff.md`.

## Artifact Index
- DISPATCH.md — record of dispatches
- BRIEFING.md — persistent working memory
- progress.md — liveness heartbeat
- handoff.md — final handoff report
