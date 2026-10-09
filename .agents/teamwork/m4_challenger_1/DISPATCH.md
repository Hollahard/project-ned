# DISPATCH — m4_challenger_1

## Task Assignment
Milestone 4: Process Guardian & Security Containment Verification (R4) — Challenger 1 (Capability Tokens & HWND Adversarial Stress).

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1\handoff.md`

## Empirical Challenge Tasks
- Empirically challenge Capability Token security:
  * Replay attack challenge: verify immediate rejection if the exact same token is used a second time.
  * HWND binding challenge: verify that presenting a valid token minted for HWND A fails when consumed by HWND B.
  * Argument tampering challenge: verify that modifying even 1 byte/key in arguments rejects token with `ArgHashMismatch`.
  * Expiration challenge: verify tokens expire after 120s TTL and are rejected.
  * JSON canonicalization: verify key ordering invariance (nested dictionaries, lists).
- Execute Rust supervisor unit tests in `apps/desktop/src-tauri` and Python security tests in `tests/security/test_capability_tokens.py`.
- Follow GEMINI.md routing strictly: temporary log files, inspect via `view_file`, delete.

## Output
Write your empirical challenge report and verdict (`APPROVE` or `REQUEST_CHANGES`) to:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_1\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.
