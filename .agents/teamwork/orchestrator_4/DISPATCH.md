# Dispatch Assignment — Orchestrator Generation 4 (orchestrator_4)

## Identity & Lineage
- Archetype: orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_4`
- Generation: 4
- Predecessor: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)
- Parent Conversation ID: `3ac1c658-7ee5-4db5-8f22-71f84677240a` (Sentinel / Top-Level Parent)

## Mission
Continue and complete Project Ned Native Desktop Integration from checkpoint commit `2afa8ea`:
- Milestone 1: DONE & GATE PASSED
- Milestone 2: DONE & GATE PASSED
- Milestone 3: IMPLEMENTED by `worker_m3_1` (11 vector tests, 196 core tests pass, ruff clean). Action: Run Verification Gate (2 Reviewers, 2 Challengers, 1 Forensic Auditor).
- Milestone 4: PLANNED (Process Guardian Job Object 0x2000, environment sanitization, HMAC tokens bound to HWND, `.no_proxy()` loopback fix, baseline dirty file preservation).
- Milestone 5: PLANNED (Final multi-suite qualification and Sentinel handoff).

## Immediate Next Steps
1. Read predecessor state files:
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\handoff.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\BRIEFING.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\GATE_STATUS.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\progress.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md`
   - `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
2. Start heartbeat cron `schedule(CronExpression="*/10 * * * *", Prompt="Heartbeat: check subagent progress and update progress.md")`.
3. Dispatch Milestone 3 verification loop:
   - 2 Reviewers (`teamwork_preview_reviewer`)
   - 2 Challengers (`teamwork_preview_challenger`)
   - 1 Forensic Auditor (`teamwork_preview_auditor`)
4. Reconcile Gate in `GATE_STATUS.md`. When passed, set M3 to DONE in `PROJECT.md`.
5. Dispatch Worker for Milestone 4, run M4 verification loop and gate check.
6. Run Milestone 5 full qualification and Sentinel handoff.
