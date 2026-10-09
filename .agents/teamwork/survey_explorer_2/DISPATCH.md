# Dispatch — Survey Explorer 2 (Transport, Sockets & Vendor Integrity)

## Identity
- Archetype: teamwork_preview_explorer
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective
Investigate the technical implementation landscape and status for Requirements R1 and R2:
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (section `## 2026-10-09T13:42:19Z`)
2. Examine `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` and manifest `socket-candidates-20261008.json`. What files are in the zip, where do they belong, and what needs promotion?
3. Investigate TypeScript strict check error TS2367 in `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`. What is the exact type mismatch / narrowed state bug?
4. Investigate the 28 vendored Tungstenite 0.30.0 output files: where are they located, what are their expected hashes, newline conventions, and status?
5. Investigate parser progress safety invariants: how are fatal protocol errors, peer close, and message ordering currently handled?
6. Investigate the test suites:
   - 19 owned-ws tests
   - 7 owned-http tests
   - 8 parser progress tests
   - 8 Python vendor-tamper tests (`test_vendor_integrity.py`)
   - `hermes-native/scripts/Verify-Foundation.ps1` (current content, test coverage, how it runs, and how it needs to be expanded).

## Scope Boundaries
- Read-only investigation. DO NOT modify any code or test files.
- Deliver your findings in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2\handoff.md`.
- Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.

## 2026-10-09T13:49:55Z
You are Survey Explorer 2 for Project Ned native desktop integration (Transport, Sockets & Vendor Integrity).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2\DISPATCH.md

Your mission:
Investigate requirements R1 and R2 at the code and test level:
- docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip & socket-candidates-20261008.json: inspect what files are present, hashes, and where they should be unpacked/promoted.
- hermes-native/apps/desktop-ui/src/native-gateway-socket.ts: inspect the TS2367 type error (narrowed CONNECTING vs CLOSING).
- Vendored Tungstenite 0.30.0 output files (28 files): locate them, inspect hashes and newline integrity.
- Parser progress safety: check protocol error handling, peer close, and message ordering.
- Test suites: locate and examine the 19 owned-ws tests, 7 owned-http tests, 8 parser progress tests, and 8 vendor-tamper tests in test_vendor_integrity.py.
- Inspect hermes-native/scripts/Verify-Foundation.ps1 to see what it currently verifies and what needs to be added.

Deliver your report in: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2\handoff.md
When done, notify your parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d.
