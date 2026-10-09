# Dispatch — Challenger 1 for Milestone 2

## Identity
- Archetype: teamwork_preview_challenger
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_challenger_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective: Adversarial Stress Testing of Milestone 2 Transports
Adversarially challenge Requirement R2:
1. **Owned WebSocket and Parser Progress Stress**:
   - Stress-test the 19 owned-ws tests and 8 parser progress tests under concurrency and continuous cycles.
   - Verify that TCP sockets close cleanly and zero orphaned processes linger in the process table.
2. **Owned HTTP Stress**:
   - Run the 7 owned-http tests, testing malformed responses, slow trickles, and bounded operation deadlines.
3. **Foundation Script Gate Robustness**:
   - Verify that `Verify-Foundation.ps1` fails closed if vendor verifier, vendor tamper tests, or linters fail.

Follow GEMINI.md: route test outputs through temp logs and clean up.
Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_challenger_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d`.
## 2026-10-09T14:54:01Z
You are Challenger 1 for Milestone 2: Owned WebSocket & Transport Foundation Verification.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_challenger_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_challenger_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m2_1\handoff.md

Empirically challenge:
- Multi-cycle stress of owned-ws (19 tests) and owned-http (7 tests).
- Verify zero orphaned processes, zero socket leaks, and zero thread hangs.
- Verify fail-closed behavior of Verify-Foundation.ps1 if vendor verification fails.

Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_challenger_1\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
