# Dispatch — M2 Explorer 3
Target: Milestone 2 (Rust Tauri Supervisor Endurance Contract: apps/desktop/src-tauri)
Focus: Deep investigation of cargo test targets, Cargo.toml dependencies, Win32 API features in windows-sys, and integration test structure for tests/test_endurance_invariants.rs.

## 2026-10-07T16:06:13Z
From: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 (orchestrator_1)
Content:
You are Explorer 3 for Milestone 2 (Rust Tauri Supervisor Endurance Contract).
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_3.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\GEMINI.md
4. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_survey_3\handoff.md
5. G:\Project_Ned\apps\desktop\src-tauri\Cargo.toml

Your objective:
Focus on the crate structure, Cargo.toml feature dependencies, compilation commands, and test integration:
1. Inspect `apps/desktop/src-tauri/Cargo.toml`. Verify features required for `windows-sys` (e.g. `Win32_System_JobObjects`, `Win32_System_Threading`, `Win32_System_Diagnostics_ToolHelp`, `Win32_Foundation`).
2. Verify how `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` executes and whether `tests/test_endurance_invariants.rs` integrates cleanly into the cargo test runner.
3. Formulate the exact build, test, and verification commands per GEMINI.md.

Scope boundaries:
- Read-only analysis. Recommend fix strategy, do NOT implement.
- Write your comprehensive report in G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_3\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
