## 2026-10-07T17:04:12Z
You are Explorer 1 for Milestone 3: Standalone Long-Run Endurance Runner.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md (Authoritative ADR-0002)
4. G:\Project_Ned\GEMINI.md
5. Existing soak runner / tests in G:\Project_Ned\tests\soak\

Your objective:
Focus on the CLI, Architecture, and Process Lifecycle for `tests/soak/run_8hr_soak.py`:
1. Design the CLI argument parser:
   - Modes: `--mode smoke` (15m duration), `--mode gate` (1h duration), `--mode release` (8h duration).
   - Flags for `--warmup-minutes` (default 15m for gate/release, or scaled e.g. 3m for smoke or configurable), `--sample-interval-seconds` (default e.g. 5s or 10s), `--output-dir` (default `logs/`), `--report-dir` (default `docs/benchmarks/`), `--headless` (default True).
2. Design process orchestration:
   - How does the runner interact with the target system?
   - Can it target an already-running Core / TabbyAPI instance or spawn them in mock/live mode?
   - How is the Windows Job Object used to supervise child processes if spawned by the runner?
   - How is graceful shutdown handled (SIGINT / CTRL+C / timeout) to ensure zero orphaned processes?
3. Provide a complete, modular blueprint for the runner's main loop and CLI entrypoint.

Scope boundaries:
- Read-only analysis. Recommend implementation architecture and blueprints, do NOT modify code.
- Write your comprehensive report in G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_1\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
