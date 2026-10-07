# BRIEFING — 2026-10-07T17:11:30Z

## Mission
Analyze, architect, and provide concrete implementation blueprints for Fault Injections, VRAM Recovery Oracle, Benchmark Reporting, and Smoke Mode calibration for `tests/soak/run_8hr_soak.py`.

## 🔒 My Identity
- Archetype: explorer
- Roles: [investigator, architect, reporter]
- Working directory: G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3
- Original parent: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Milestone: Milestone 3: Standalone Long-Run Endurance Runner

## 🔒 Key Constraints
- Read-only investigation — do NOT implement / modify source code outside our agent directory
- Output comprehensive report to `handoff.md`
- Focus specifically on:
  1. Scripted fault injections (Gaming Mode VRAM evacuation <= 2.0s, mid-turn cancel, Job Object sidecar restarts)
  2. VRAM Recovery Oracle (baselines, 512 MB residual delta check, pre-launch baseline exit check)
  3. Reporting & artifact generation (`logs/soak_results.json`, `docs/benchmarks/soak_test_report.md` with RTX 5090 specs)
  4. Smoke test calibration (~15 min runtime with scaled warmup/duration)

## Current Parent
- Conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `tests/soak/run_8hr_soak.py`: Existing long-run soak harness implementation (986 lines).
  - `tests/soak/test_soak_endurance.py`: Verified fast soak suite (816 lines).
  - `services/core/src/friday/inference/gaming_mode.py`: `GamingModeController` and `GamingModeStatus`.
  - `services/core/src/friday/agent/loop.py`: `AgentLoop` cancellation protocol, streaming events, and `_active_cancels`.
  - `apps/desktop/src-tauri/src/processes.rs` & `services/core/src/friday/skills/cage.py`: Windows Job Object structures (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), accounting, and lifecycle.
  - `services/core/src/friday/inference/telemetry.py`: NVML hardware telemetry provider and `pynvml` bindings.
  - `docs/adr/0002-continuous-soak-and-endurance-testing.md`: Authoritative ADR-0002 endurance testing specification.
  - `docs/benchmarks/soak_test_report.md` & `logs/soak_results.json`: Existing artifact outputs.
  - `g:\Project_Ned\.agents\skills\project-friday-ops\SKILL.md`: Hardware environment specification for RTX 5090 Blackwell.
- **Key findings**:
  1. CLI choices in `run_8hr_soak.py` currently only allow `["15m", "1h", "8h", "custom"]`, which fails the required `--mode smoke` invocation.
  2. Gaming mode in `run_8hr_soak.py` only calls `unload_model()` directly, without asserting the 2.0s deadline or checking turn rejection while active.
  3. Mid-turn cancel does not assert zero leaked tasks (`asyncio.all_tasks()`) or immediate recovery.
  4. MCP restart currently only re-instantiates an in-memory tool registry, rather than validating process kill and restart inside a Windows Job Object.
  5. VRAM recovery oracle does not track pre-launch baseline, does not attribute to Tabby PID when running as separate process, does not verify post-exit return to pre-launch baseline, and does not check monotonic unload creep.
  6. Smoke mode calibration requires a 10s sampling interval and a 3m (180s) warmup cutoff to allow 12m of statistically valid regression analysis.
- **Unexplored areas**: None within Explorer 3 scope.

## Key Decisions Made
- Architected drop-in modular classes: `GamingModeFaultInjector`, `MidTurnCancelFaultInjector`, `JobObjectSidecarFaultInjector`, `VramRecoveryOracle`, `ArtifactGenerator`, and `SmokeModeCalibrator`.
- Writing comprehensive 5-component handoff report to `handoff.md`.

## Artifact Index
- `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\DISPATCH.md` — Inbound message log
- `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\BRIEFING.md` — Persistent working memory
- `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\progress.md` — Liveness heartbeat
- `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_3\handoff.md` — Final deliverable report
