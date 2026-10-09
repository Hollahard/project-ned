# Dispatch — Reviewer 1 for Milestone 1

## Identity
- Archetype: teamwork_preview_reviewer
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_reviewer_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Review Scope: Milestone 1
Verify Milestone 1 deliverables against `ORIGINAL_REQUEST.md` (## 2026-10-09T13:42:19Z) and `PROJECT.md`:
1. Candidate socket actor promotion from `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` & manifest `socket-candidates-20261008.json`.
2. TypeScript strict check TS2367 fix in `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`.
3. Peer-close host retirement invariant: remote close must not prematurely certify actor retirement (`#nativeRetired = true`). Preceding frames must be drained in wire order.
4. Vendored Tungstenite 0.30.0: 28 files reconstructed under `hermes-progress-2` receipt with LF/CRLF integrity and hash verification.
5. Parser progress safety and sticky error latching on protocol errors.

## Mandatory Rules
- Follow GEMINI.md: pipe test commands to temp log files `cmd.exe /c "..." > log.txt 2>&1`, inspect via view_file, and delete after inspection.
- Independent test execution:
  * TypeScript strict typecheck via node tsc
  * `python hermes-native/services/owned-ws/verify_vendor.py`
  * `pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v`
  * `cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1`
  * `cargo test --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1`

Deliver your verdict (APPROVE or REQUEST_CHANGES) in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_reviewer_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d`.


## 2026-10-09T14:25:54Z
You are Reviewer 1 for Milestone 1: Candidate Socket Promotion & Client Typecheck Resolution.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_reviewer_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_reviewer_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1\handoff.md

Review tasks:
- Inspect all modified/promoted files for correctness, completeness, and interface compliance.
- Independently execute and verify:
  * TypeScript strict typecheck on native-gateway-socket.ts
  * verify_vendor.py (28 files verified)
  * test_vendor_integrity.py (8/8 tests pass)
  * owned-ws cargo test (19/19 tests pass)
- Verify peer-close host retirement invariant and message ordering.

Deliver your review verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_reviewer_1\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
