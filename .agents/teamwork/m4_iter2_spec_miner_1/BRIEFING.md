# BRIEFING — 2026-10-09T16:42:00Z

## Mission
Mine and document all formal requirements, specifications, and test contracts regarding process environment sanitization for Milestone 4 Iteration 2.

## 🔒 My Identity
- Archetype: specification-miner
- Roles: Teamwork specialist, Specification Miner
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Milestone: Milestone 4 Iteration 2 (Process Sanitization Invariants)

## 🔒 Key Constraints
- Read-only: DO NOT implement changes yourself. Only document specifications and requirements.
- Never write API keys, secrets, or hardcoded credentials.
- Adhere to GEMINI.md Rule 2: Process Guardian & Sidecar Invariants (Environment Sanitization: Never copy std::env::vars() or os.environ wholesale to child processes. Strip parent secrets and pass only explicit whitelist variables (PATH, TEMP, SYSTEMROOT) and process tokens).
- Route all test commands to output files via cmd.exe /c (GEMINI.md Rule 1).

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: not yet

## Task Summary
- **What to build**: Specification report on process environment sanitization in Rust Tauri Supervisor and Python Core.
- **Success criteria**: Comprehensive handoff.md detailing Win32 CreateProcessW vs std::process::Command env inheritance, exact whitelist variables for Windows subsystem and Python runtime, acceptance criteria, and verification commands.
- **Interface contracts**: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
- **Code layout**: apps/desktop/src-tauri/ (supervisor), services/core/ (Python Core)

## Key Decisions Made
- Confirmed root cause of leak: Rust's std::process::Command::envs merges with parent environment unless env_clear() is called prior.
- Mined complete Win32 CreateProcessW lpEnvironment block mechanics and ordering constraints.
- Documented exact 12-variable Windows subsystem whitelist (ALLOWED_VARS) and 5 injected runtime variables, explaining why each is necessary and consequences of omission.
- Defined formal pass/fail acceptance criteria and verification commands for M4 Iteration 2.

## Loaded Skills
- **Source**: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md
- **Local copy**: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md
- **Core methodology**: Operational runbook for Project Friday testing, multi-stack verification on Windows.

## Artifact Index
- handoff.md — Final specification report
- progress.md — Liveness heartbeat and progress log
