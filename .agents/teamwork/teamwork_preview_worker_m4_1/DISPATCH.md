## 2026-10-07T17:49:27Z
You are the Worker for Milestone 4: Dual Track Acceptance Verification & Final Qualification.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m4_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md
4. G:\Project_Ned\GEMINI.md (Strict workspace rules: cmd.exe /c test output piping, PowerShell escaping, zero orphaned processes)
5. G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m1_1\handoff.md
6. G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m2_1\handoff.md
7. G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m3_1\handoff.md

Objective:
Execute the comprehensive end-to-end acceptance qualification for Project Friday Phase 16:
1. Execute Fast Mocked Soak Suite:
   `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > m4_pytest_soak.txt 2>&1"`
   Inspect `m4_pytest_soak.txt` with view_file: verify all 5 tests pass in < 3 minutes, then delete `m4_pytest_soak.txt`.
2. Execute Rust Tauri Supervisor Suite:
   `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > m4_cargo_test.txt 2>&1"`
   Inspect `m4_cargo_test.txt` with view_file: verify all 15 tests pass (0 failures, 0 warnings), then delete `m4_cargo_test.txt`.
3. Execute Full Core Regression Suite:
   `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > m4_pytest_regression.txt 2>&1"`
   Inspect `m4_pytest_regression.txt` with view_file: verify 216+ tests pass, then delete `m4_pytest_regression.txt`.
4. Execute Standalone Endurance Smoke Qualification:
   `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke --gpu > m4_soak_smoke.txt 2>&1"`
   (If smoke takes ~15m, you may also run a calibrated qualification like `--mode custom --duration-minutes 1.0 --warmup-minutes 0.2 --sample-interval-seconds 2 --gpu > m4_soak_custom.txt 2>&1` to demonstrate full multi-fault and NVML evaluation on the NVIDIA RTX 5090).
   Inspect the log with view_file, verify all tripwires pass and all faults pass, then delete the log file.
5. Verify zero orphaned processes:
   `cmd.exe /c "tasklist | findstr /i ping.exe"` returns exit code 1.
6. Verify and summarize the generated artifacts:
   - `logs/soak_results.json`
   - `docs/benchmarks/soak_test_report.md`
   - `logs/traces/*.jsonl`
7. Formulate full verification report with Observation, Logic Chain, Caveats, Conclusion, and Verification Method.
8. Deliver your results in G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m4_1\handoff.md.
9. Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
