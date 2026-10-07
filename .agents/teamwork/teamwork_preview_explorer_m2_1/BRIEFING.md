# BRIEFING — 2026-10-07T16:13:30Z

## Mission
Investigate Windows Job Object concurrency and termination invariants in apps/desktop/src-tauri/src/processes.rs, propose handle/limits exposure, and design test_job_object_limits_permit_concurrency_and_kill_on_close.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, analyst
- Working directory: G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_1
- Original parent: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Milestone: Milestone 2 (Rust Tauri Supervisor Endurance Contract)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Focus on Windows Job Object concurrency and termination invariants in apps/desktop/src-tauri
- Propose accessor/method to expose raw handle or query limits
- Design test test_job_object_limits_permit_concurrency_and_kill_on_close in tests/test_endurance_invariants.rs
- Output comprehensive handoff report to G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_1\handoff.md

## Current Parent
- Conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Updated: 2026-10-07T16:10:28Z

## Investigation State
- **Explored paths**:
  - `apps/desktop/src-tauri/src/processes.rs` (JobObject struct, new, assign, contains_process, query_active_process_count, handle, terminate, drop)
  - `apps/desktop/src-tauri/Cargo.toml` (windows-sys 0.59 features, dependencies, test config)
  - `apps/desktop/src-tauri/tests/test_job_object.rs` (baseline assign and drop assertions)
  - `apps/desktop/src-tauri/tests/test_supervisor_soak.rs` (multi-process sidecar reaping, handle count sampling)
  - `.agents/teamwork/teamwork_preview_explorer_survey_3/handoff.md` (Tauri survey)
  - `.agents/teamwork/orchestrator_1/PROJECT.md` (M2 specifications)
- **Key findings**:
  - `processes.rs:62-72` zeroes `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` and explicitly sets only `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x2000). `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (0x08) is strictly 0 and `ActiveProcessLimit` is 0, ensuring unlimited process concurrency inside the job cage.
  - `JobObject` currently exposes `pub fn handle(&self) -> HANDLE`. Adding `pub fn raw_handle(&self) -> HANDLE`, implementing `std::os::windows::io::AsRawHandle`, and providing `pub fn query_extended_limits(&self)` provides full ergonomic flexibility and safe query options.
  - Test `test_job_object_limits_permit_concurrency_and_kill_on_close` design completes the endurance contract by asserting query limits with `QueryInformationJobObject`, spawning 3 concurrent `cmd.exe /c ping` workers, confirming joint membership, dropping the job, and verifying clean asynchronous kernel reaping.
- **Unexplored areas**: none within Explorer 1 scope.

## Key Decisions Made
- Confirmed bitmask values and Win32 kernel semantics for active process quota vs kill-on-close.
- Recommended triple accessor strategy (`raw_handle()`, `impl AsRawHandle`, and safe `query_extended_limits()`).
- Designed self-contained test implementation with timeout polling and hung process cleanup.

## Artifact Index
- DISPATCH.md — Dispatch log with parent messages
- BRIEFING.md — Persistent working memory
- progress.md — Liveness heartbeat
- handoff.md — 5-component handoff report
