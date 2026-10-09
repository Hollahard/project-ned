# DISPATCH — m4_challenger_2

## Task Assignment
Milestone 4: Process Guardian & Security Containment Verification (R4) — Challenger 2 (Job Object Containment, Concurrency & Proxy Loopback Stress).

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_2`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m4_1\handoff.md`

## Empirical Challenge Tasks
- Empirically challenge Process Guardian containment:
  * Concurrency: verify multiple child worker processes run concurrently under Windows Job Object (`ActiveProcessLimit == 0`).
  * Kill-on-close: verify that closing/dropping the job object handle kills all assigned child processes (`0x2000`).
  * Environment sanitization: verify that parent environment variables (like API keys, test secrets) are completely absent from child processes.
  * Loopback Proxy Bypass: verify that loopback HTTP requests succeed and are not proxied or blocked with HTTP 400.
  * Zero orphan processes post-execution via `tasklist`.
- Execute multi-cycle stress runs:
  * `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml`
  * `pytest tests/soak/test_adversarial_cli_lifecycle.py -v`
  * `pytest tests/soak/test_soak_endurance.py -v -m soak`
- Follow GEMINI.md routing strictly: temporary log files, inspect via `view_file`, delete.

## Output
Write your empirical challenge report and verdict (`APPROVE` or `REQUEST_CHANGES`) to:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_2\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.

## 2026-10-09T16:17:24Z
[Message] timestamp=2026-10-09T16:17:24Z sender=635b9360-b27f-4ffc-82d0-46001e560e8d priority=MESSAGE_PRIORITY_HIGH content=You are Challenger 2 for Milestone 4 (Job Object Containment, Concurrency & Proxy Loopback Stress).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_2
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

