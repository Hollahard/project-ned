# Dispatch Assignment — m3_challenger_1

## Mission
Adversarial Challenge for Milestone 3: Canonical Invalidation (F02) & Crash Recovery (F03).

## Context & Inputs
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (MANDATORY: read Section `## 2026-10-09T13:42:19Z` first!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m3_1\handoff.md`
5. Target files in `services/core/src/friday/memory/`, `services/core/src/friday/storage/`, and `services/core/tests/`.

## Empirical Challenge Tasks
- Empirically challenge F02 canonical validity:
  * Soft-delete a message in canonical `messages`: verify vector search immediately drops it from recall.
  * Delete a session in canonical `sessions`: verify all associated messages are excluded from recall.
  * Rewind a session: verify rewound messages become ineligible.
  * Verify that identical text in two messages has distinct provenance and deleting one does NOT drop the other.
- Empirically challenge F03 crash recovery:
  * Inject records into canonical tables without vector ingestion; run `ReconciliationEngine.reconcile_canonical` and verify they are indexed.
  * Test duplicate execution of reconciliation and verify idempotency (zero duplicated chunks).
- Run multi-cycle test runs following GEMINI.md.

Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m3_challenger_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d`.


## 2026-10-09T15:37:51Z
You are Challenger 1 for Milestone 3 (Canonical Invalidation F02 & Crash Recovery F03).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m3_challenger_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m3_challenger_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m3_1\handoff.md

Empirical Challenge Tasks:
- Empirically challenge F02 canonical validity:
  * Soft-delete a message in canonical messages: verify vector search immediately drops it from recall.
  * Delete a session in canonical sessions: verify all associated messages are excluded from recall.
  * Rewind a session: verify rewound messages become ineligible.
  * Verify that identical text in two messages has distinct provenance and deleting one does NOT drop the other.
- Empirically challenge F03 crash recovery:
  * Inject records into canonical tables without vector ingestion; run ReconciliationEngine.reconcile_canonical and verify they are indexed.
  * Test duplicate execution of reconciliation and verify idempotency (zero duplicated chunks).
- Run multi-cycle test runs following GEMINI.md.

Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m3_challenger_1\handoff.md
Notify parent via send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
