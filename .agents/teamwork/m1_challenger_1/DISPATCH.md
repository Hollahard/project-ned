# Dispatch — Challenger 1 for Milestone 1

## Identity
- Archetype: teamwork_preview_challenger
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective: Adversarial Stress Testing of Milestone 1
Empirically stress-test Requirement R1:
1. **Parser Progress Safety**:
   - Fatal protocol error latching: test whether corrupt, malformed, or out-of-order WebSocket frames latch the sticky error flag in `InputProgress` and never synthesize valid application state.
   - Message ordering: test that preceding messages in `#incoming` queue are strictly dispatched ahead of terminal `CloseEvent`.
2. **Peer Close Boundary**:
   - Test that observing peer close frame does NOT cause actor retirement without host retirement receipt (`receipt.retired === true`).
3. **TypeScript & Client Edge Cases**:
   - Test state transitions in `NativeGatewaySocket`: concurrent `#start()` and `close()`, rapid close during connection, invalid identity responses.

Follow GEMINI.md: route test outputs through temp logs and clean up.
Deliver your empirical verification verdict (APPROVE or REQUEST_CHANGES) in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d`.
## 2026-10-09T14:25:54Z
You are Challenger 1 for Milestone 1 (Parser Progress Safety & Client Stress Testing).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1\handoff.md

Empirically challenge:
- Fatal protocol error latching: verify that once a fatal protocol error occurs, subsequent observations fail and never synthesize valid state.
- Wire order delivery: verify preceding frames in #incoming are delivered before CloseEvent.
- Peer close actor retirement: verify that remote close does not self-certify actor retirement without host receipt.
- Run tests and adversarial checks following GEMINI.md.

Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_1\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
