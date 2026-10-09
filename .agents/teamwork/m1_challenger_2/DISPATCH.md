# Dispatch — Challenger 2 for Milestone 1

## Identity
- Archetype: teamwork_preview_challenger
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_2`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective: Vendor Tamper & Transport Verification
Adversarially challenge Requirement R1:
1. **Vendor Integrity**:
   - Verify that all 28 Tungstenite 0.30.0 vendor files match expected preimages and LF/CRLF newline conventions.
   - Test tamper resistance: simulate extra unlisted file, wrong revision, tampered bytes, parent traversal path, and confirm `test_vendor_integrity.py` and `verify_vendor.py` catch all violations.
2. **Transport Conformance**:
   - Run the full 19 owned-ws tests and 7 owned-http tests.
   - Verify that no socket leaks or unhandled thread panics occur.

Follow GEMINI.md: route test outputs through temp logs and clean up.
Deliver your empirical verification verdict (APPROVE or REQUEST_CHANGES) in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_2\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d`.

## 2026-10-09T14:25:54Z
You are Challenger 2 for Milestone 1 (Vendor Tamper & Transport Verification).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_2
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_2\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1\handoff.md

Empirically challenge:
- Vendor integrity and tamper resistance: test that extra files, tampered preimages, wrong revisions, or parent traversals are detected by test_vendor_integrity.py and verify_vendor.py.
- Execute full 19 owned-ws tests and 7 owned-http tests.
- Confirm zero thread hangs or socket leaks.

Deliver your empirical verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m1_challenger_2\handoff.md
Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
