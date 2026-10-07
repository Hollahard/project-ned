## 2026-10-07T15:12:07Z
You are the Rust Tauri Supervisor Explorer for Project Friday Phase 16 Soak and Endurance.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_survey_3.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Task:
Read and deeply analyze:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\GEMINI.md (Process guardian & sidecar invariants, Job Object limits, cmd test piping)
3. G:\Project_Ned\apps\desktop\src-tauri (Cargo.toml, src/, tests/)

Investigate:
- Supervisor process management: How is the Windows Job Object created, configured, and bound?
- Verify `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is used and verify that `ActiveProcessLimit = 1` / `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is NOT set.
- How are session creation, telemetry polling, and preflight checks implemented in the supervisor?
- How to add Rust integration tests verifying:
  a. Repeated session creation, telemetry polling, preflight checks do not leak Windows OS handles or thread pools.
  b. Supervisor window close cleanly terminates child processes without breaking worker concurrency.
- How `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` is executed and what dependencies/modules are involved.

Scope boundaries:
- Read-only analysis. Do NOT modify source code.
- Write your comprehensive report in G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_survey_3\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
