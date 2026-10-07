## 2026-10-07T16:23:22Z

You are the Worker for Milestone 2: Rust Tauri Supervisor Endurance Contract.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m2_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\GEMINI.md (Strict workspace rules: cmd.exe /c test piping, PowerShell escaping, zero orphaned processes)
4. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_1\handoff.md (Job Object concurrency blueprint)
5. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_2\handoff.md (Handle & thread leak blueprint)
6. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_3\handoff.md (Crate structure & integration blueprint)

Write Ownership:
You have EXCLUSIVE write ownership of:
- G:\Project_Ned\apps\desktop\src-tauri\src\processes.rs (adding raw_handle and AsRawHandle)
- G:\Project_Ned\apps\desktop\src-tauri\tests\test_endurance_invariants.rs (creating new integration test file)
DO NOT touch any other files unless strictly required.

Objective:
1. In `apps/desktop/src-tauri/src/processes.rs`:
   - Add `pub fn raw_handle(&self) -> HANDLE { self.handle }`.
   - Implement `std::os::windows::io::AsRawHandle` for `JobObject`:
     ```rust
     impl std::os::windows::io::AsRawHandle for JobObject {
         fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
             self.handle as _
         }
     }
     ```
2. Create `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`:
   - Include both tests guarded by `static ENDURANCE_SERIALIZATION_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());`:
     a. `test_job_object_limits_permit_concurrency_and_kill_on_close`:
        - Assert `QueryInformationJobObject` confirms `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0`, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`, and `ActiveProcessLimit == 0`.
        - Spawn 3 concurrent child worker processes (`cmd.exe /c ping 127.0.0.1 -n 30`).
        - Assign all 3 to Job Object, verify membership and `query_active_process_count >= 3`.
        - Drop `JobObject`, poll up to 3 seconds for clean termination (`child.try_wait() == Ok(Some(_))`), assert 0 orphans.
     b. `test_supervisor_repeated_operations_no_handle_or_thread_leak`:
        - Run in-memory loopback mock HTTP server (`127.0.0.1:0`) handling `/api/v1/sessions`, `/api/v1/telemetry/gpu`, `/api/v1/models/preflight` with keep-alive.
        - Run 10 warmup cycles, then sample baseline handles (`GetProcessHandleCount`) and threads (`CreateToolhelp32Snapshot`).
        - Run 50 continuous iterations of `proxy.create_session`, `proxy.get_gpu_telemetry`, `proxy.check_vram_preflight`, and `run_preflight_diagnostics`.
        - Sample final metrics and assert `handle_delta <= 5` and `thread_delta <= 1`.
        - Cleanly shut down mock server.

Verification Step:
Execute following GEMINI.md:
`cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test_run.txt 2>&1"`
Inspect `cargo_test_run.txt` with view_file, verify all 15 tests pass (0 failures, 0 warnings), then delete `cargo_test_run.txt`.

Deliver your findings in G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m2_1\handoff.md.
Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
