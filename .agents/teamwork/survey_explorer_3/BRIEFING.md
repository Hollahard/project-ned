# BRIEFING — 2026-10-09T14:07:30Z

## Mission
Investigate Requirements R3 (Memory & Vector DB) and R4 (Process Guardian, Windows Job Object containment, Credential isolation) across Project Ned repository.

## 🔒 My Identity
- Archetype: teamwork_preview_explorer
- Roles: explorer, investigator, synthesizer
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Milestone: R3 & R4 Architectural and Code Survey

## 🔒 Key Constraints
- Read-only investigation — do NOT implement or modify workspace code/tests
- Strict adherence to Project Ned workspace rules in GEMINI.md
- Deliver 5-component handoff report to c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\handoff.md
- Notify parent (635b9360-b27f-4ffc-82d0-46001e560e8d) via send_message upon completion

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: 2026-10-09T13:49:55Z

## Investigation State
- **Explored paths**:
  - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\services\core\` (memory, storage, security, tests)
  - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\apps\desktop\` (src, src-tauri, tests)
  - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\hermes-native\` (services, spikes, scripts)
  - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\tests\` (security, soak, e2e)
  - `G:\Project_Ned\` and `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`
- **Key findings**:
  1. `preexisting-dirty-file-hashes.json` located at `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`. Contains 4 files (`apps/desktop/src-tauri/src/lib.rs`, `proxy.rs`, `tauri.conf.json`, `vite.config.ts`). In `G:\Project_Ned`, all 4 match hashes exactly. In worktree `C:\...`, working tree is clean with respect to commit `2afa8ea`.
  2. Memory subsystem in `services/core/src/friday/memory/` is a 4-tier memory architecture (Working, Episodic, Semantic, Procedural) with FTS5 search. `sqlite-vec` is not yet installed or integrated; must be implemented in M3 per ADR05/F02/F03 (hybrid FTS + `vec0`, CPU embeddings, canonical deletion/rewind invalidation, outbox reconciliation).
  3. Async SQLite connection management in `services/core/src/friday/storage/db.py` uses `aiosqlite`. All 185 tests in `services/core/tests/` use async `yield` fixtures awaiting `db_manager.close()`, passing in 19.30s without worker thread hangs.
  4. Process Guardian implemented in Rust (`apps/desktop/src-tauri/src/processes.rs`) with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`, `ActiveProcessLimit == 0` (omits `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`), and strict whitelist `build_sanitized_env`.
  5. Credential isolation uses HMAC-SHA256 capability tokens (120s TTL, single-use, canonical argument hash). Zero bearer tokens reach WebView2 frontend. In `desktop-shell`, main window HWND is bound and checked via atomic CAS. In `approvals.rs`, `MessageBoxW` currently uses `null_mut()` and should bind to main window HWND.
  6. Discovered loopback proxy issue in `apps/desktop/src-tauri/src/proxy.rs`: `reqwest::Client` needs `.no_proxy()` to bypass Windows system/corporate proxy on `127.0.0.1`.
- **Unexplored areas**: None for survey scope.

## Key Decisions Made
- Fully surveyed R3, R4, dirty file baseline, and test suites.
- Completed comprehensive 5-component handoff report.

## Artifact Index
- DISPATCH.md — incoming dispatch instructions and mission definition
- BRIEFING.md — persistent working memory
- progress.md — liveness heartbeat
- handoff.md — final 5-component handoff report
