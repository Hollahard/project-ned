# DISPATCH — m5_challenger_2

## Task Assignment
Milestone 5 Challenger 2: Process Guardian, Soak Endurance & Security Empirical Challenge.

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_challenger_2`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m5_1\handoff.md`

## Empirical Challenge Tasks
Empirically challenge supervisor resilience, soak endurance, and security containment:
1. Multi-cycle execution of soak endurance suite (`pytest tests/soak/test_soak_endurance.py -v -m soak`).
2. Adversarial CLI lifecycle test suite (`pytest tests/soak/test_adversarial_cli_lifecycle.py -v`).
3. Security red-team vectors (`pytest tests/security/ -v`).
4. Windows Job Object containment challenge: verify child processes are terminated upon parent kill (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`).
5. Environment sanitization challenge: verify hostile parent secrets are stripped in child processes with `.env_clear()`.
6. Confirm zero orphaned processes post-execution via tasklist.

## Output
Deliver your empirical challenge report and verdict (APPROVE or REQUEST_CHANGES) in:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_challenger_2\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.

## 2026-10-09T17:14:16Z
[Message] timestamp=2026-10-09T17:14:16Z sender=635b9360-b27f-4ffc-82d0-46001e560e8d priority=MESSAGE_PRIORITY_HIGH content=You are Challenger 2 for Milestone 5: Process Guardian, Soak Endurance & Security Empirical Challenge.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_challenger_2
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

