# BRIEFING — 2026-10-09T16:42:00Z

## Mission
Investigate the process environment sanitization vulnerability in `apps/desktop/src-tauri/src/processes.rs` (`spawn_core` and `spawn_tabby`), explain Rust `Command::envs` merge behavior vs `env_clear()`, formulate a verified fix strategy, and confirm Windows Python/uvicorn critical environment variable requirements.

## 🔒 My Identity
- Archetype: explorer
- Roles: read-only investigation, code analysis, environment sanitization assessment
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_explorer_1
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d (orchestrator_3)
- Milestone: Milestone 4 Iteration 2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement changes in source code
- Adhere to GEMINI.md rules: Process Guardian and Environment Sanitization invariants
- Deliver structured 5-component handoff in handoff.md
- Communicate to parent via send_message

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: 2026-10-09T16:34:36Z

## Investigation State
- **Explored paths**:
  - `apps/desktop/src-tauri/src/processes.rs` (lines 174–223 `build_sanitized_env`, 280–328 `spawn_core`, 330–367 `spawn_tabby`)
  - `apps/desktop/src-tauri/src/runtime.rs` (supervisor orchestration)
  - `apps/desktop/src-tauri/tests/test_sanitized_env.rs` (in-memory unit test)
  - `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs` (empirical proof of secret leak without `env_clear`)
  - `ORIGINAL_REQUEST.md` (R4 security containment requirements)
  - `orchestrator_3/PROJECT.md` (Feature 21 and interface specifications)
  - Python/uvicorn/Windows runtime requirements under stripped environment
- **Key findings**:
  1. Rust `std::process::Command::envs(&sanitized)` merges with parent environment by default because internal `CommandEnv.clear` flag is `false`. Only keys explicitly present in `sanitized` are overwritten; all other parent environment variables (including API keys, SSH keys, shell tokens) are preserved in the Win32 `lpEnvironment` block passed to `CreateProcessW`.
  2. Calling `.env_clear()` before `.envs(&sanitized)` sets `CommandEnv.clear = true` and clears the variable map, ensuring `CreateProcessW` receives ONLY the keys present in `sanitized`.
  3. The current `build_sanitized_env` whitelist (`PATH`, `TEMP`, `TMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`, plus `VIRTUAL_ENV`, `PYTHONUNBUFFERED`, `PYTHONPATH`, and process tokens) was empirically tested and proven 100% sufficient for Winsock initialization, SSL context creation, `tempfile`, user home path resolution, multiprocessing CPU counts, and FastAPI `create_app()` startup.
  4. Fix requires inserting `.env_clear()` directly before `.envs(&sanitized)` in both `spawn_core` (line 315) and `spawn_tabby` (line 354) of `apps/desktop/src-tauri/src/processes.rs`.
- **Unexplored areas**: None. All mission aspects thoroughly analyzed and empirically verified.

## Key Decisions Made
- Confirmed fix placement and sequence: `cmd.env_clear()` must be chained immediately prior to `cmd.envs(&sanitized)`.
- Validated that no additional environment variables are missing from `build_sanitized_env` for Windows uvicorn/Python execution.
- Formulated recommendation for adding an OS-level integration assertion in `test_sanitized_env.rs`.

## Artifact Index
- DISPATCH.md — incoming dispatch instructions
- BRIEFING.md — persistent situational awareness
- progress.md — liveness heartbeat
- handoff.md — final analysis report
