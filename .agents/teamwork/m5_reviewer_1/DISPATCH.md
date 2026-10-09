# DISPATCH — m5_reviewer_1

## Task Assignment
Milestone 5 Reviewer 1: Foundation, Transport & Desktop Shell Review.

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1\handoff.md`

## Review Tasks
Independently execute and verify the transport and foundation subsystems following GEMINI.md routing:
1. `powershell -ExecutionPolicy Bypass -File hermes-native/scripts/Verify-Foundation.ps1 -NativeFixtures` (54 check groups, including 4 vendor gates).
2. `cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml` (19 tests).
3. `cargo test --offline --manifest-path hermes-native/services/owned-http/Cargo.toml` (7 tests).
4. `pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v` (8 tests).
5. Verify TypeScript typecheck on `native-gateway-socket.ts`: `node hermes-native/apps/desktop-ui/scripts/typecheck.mjs` (0 errors).
6. Verify that desktop UI truthfully reports backend unavailable.
7. Verify baseline dirty file hashes match 100%.

## Output
Deliver your review report and verdict (APPROVE or REQUEST_CHANGES) in:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.

## 2026-10-09T17:14:16Z
[Message] timestamp=2026-10-09T17:14:16Z sender=635b9360-b27f-4ffc-82d0-46001e560e8d priority=MESSAGE_PRIORITY_HIGH content=You are Reviewer 1 for Milestone 5: Foundation, Transport & Desktop Shell Review.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md (Strict workspace rules: always route test commands through temporary files cmd.exe /c "..." > log.txt 2>&1, inspect via view_file, and delete immediately).
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1\DISPATCH.md
5. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1\handoff.md

Review tasks:
Independently execute and verify the transport and foundation subsystems following GEMINI.md routing:
1. powershell -ExecutionPolicy Bypass -File hermes-native/scripts/Verify-Foundation.ps1 -NativeFixtures (54 check groups, including 4 vendor gates).
2. cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml (19 tests pass).
3. cargo test --offline --manifest-path hermes-native/services/owned-http/Cargo.toml (7 tests pass).
4. pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v (8 tests pass).
5. Verify TypeScript typecheck on native-gateway-socket.ts: node hermes-native/apps/desktop-ui/scripts/typecheck.mjs (0 errors).
6. Verify that desktop UI truthfully reports backend unavailable.
7. Verify baseline dirty file hashes match 100% in G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json.

Deliver your review report and verdict (APPROVE or REQUEST_CHANGES) in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1\handoff.md
Notify parent with send_message (Recipient: 635b9360-b27f-4ffc-82d0-46001e560e8d) when complete.
