## 2026-10-07T17:04:12Z
You are Explorer 3 for Milestone 3: Standalone Long-Run Endurance Runner.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md (Authoritative ADR-0002)
4. G:\Project_Ned\GEMINI.md
5. Existing test scripts and benchmarks in docs/benchmarks/

Your objective:
Focus on Fault Injections, VRAM Recovery Oracle, and Benchmark Reporting for `tests/soak/run_8hr_soak.py`:
1. Scripted Fault Injections:
   - Gaming Mode VRAM evacuation: simulate evacuation trigger, assert model unload and VRAM evacuation completes within 2.0s deadline.
   - Mid-turn cancel: trigger cancellation event while an inference turn is in flight; assert agent recovers and continues without hung tasks.
   - Job Object sidecar restarts: simulate sidecar process crash/kill inside Windows Job Object; assert supervisor restarts it cleanly without orphan processes.
2. VRAM Recovery Oracle:
   - Record pre-launch baseline VRAM and post-start baseline VRAM.
   - After unload / fault injection, verify residual memory returns to within 512 MB of post-start baseline.
   - On full exit, verify return to pre-launch baseline.
3. Reporting and Artifact generation:
   - Schema and content of `logs/soak_results.json` (all summary statistics, deltas, slopes, tripwire statuses).
   - Format and content of `docs/benchmarks/soak_test_report.md` (Markdown benchmark table, hardware environment NVIDIA RTX 5090 Blackwell, graphs/ascii summary, pass/fail status).
4. Smoke test calibration:
   - Ensure `--mode smoke` executes full end-to-end flow in ~15 minutes (or shorter with scaled warmup/duration) for fast validation.
Provide concrete implementations/blueprints for fault injectors, VRAM oracle, and report formatters.

Scope boundaries:
- Read-only analysis. Recommend implementation architecture and blueprints, do NOT modify code.
- Write your comprehensive report in G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
