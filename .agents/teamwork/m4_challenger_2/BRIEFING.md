# BRIEFING — 2026-10-09T16:35:00Z

## Mission
Adversarial empirical challenge of Milestone 4 Process Guardian containment, child worker concurrency, kill-on-close, environment sanitization, loopback proxy bypass, and zero-orphan invariants.

## 🔒 My Identity
- Archetype: EMPIRICAL CHALLENGER
- Roles: critic, specialist
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_2
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Milestone: Milestone 4 (R4)
- Instance: 2 of 2

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code
- Run verification code empirically — do NOT trust worker claims or logs
- GEMINI.md routing: route tests to temporary log files via cmd.exe /c, inspect via view_file, delete immediately
- PowerShell parentheses escaping and BypassSandbox: true
- Verify zero orphaned processes post-execution via tasklist
- .agents/teamwork/ holds only metadata — no source code, tests, or data files

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: 2026-10-09T16:17:24Z

## Review Scope
- **Files to review**:
  - `apps/desktop/src-tauri/src/processes.rs`
  - `apps/desktop/src-tauri/src/proxy.rs`
  - `apps/desktop/src-tauri/src/approvals.rs`
  - `apps/desktop/src-tauri/tests/test_job_object.rs`
  - `apps/desktop/src-tauri/tests/test_sanitized_env.rs`
  - `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`
  - `tests/soak/test_adversarial_cli_lifecycle.py`
  - `tests/soak/test_soak_endurance.py`
- **Interface contracts**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
- **Review criteria**: Empirical reproduction, concurrency, kill-on-close (0x2000), environment sanitization, loopback proxy bypass, zero orphans.

## Attack Surface
- **Hypotheses tested**:
  - Hypothesis 1: Windows Job Object allows unrestricted child worker concurrency when `ActiveProcessLimit == 0` (Confirmed: 6 concurrent workers verified).
  - Hypothesis 2: Win32 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` reaps all child processes upon handle drop (Confirmed: 100% clean termination, 0 orphans).
  - Hypothesis 3: CoreProxy `.no_proxy()` bypasses system and poisoned environment proxies to reach loopback endpoints (Confirmed: requests succeed even when `HTTP_PROXY` points to dead port).
  - Hypothesis 4: `Command::new().envs(&sanitized)` in Rust clears parent environment variables (Falsified: Rust stdlib `Command::envs` merges variables and does NOT strip parent environment without `.env_clear()`).
- **Vulnerabilities found**:
  - CRITICAL: In `apps/desktop/src-tauri/src/processes.rs` (`spawn_core` line 315 and `spawn_tabby` line 354), `Command::new` calls `.envs(&sanitized)` without `.env_clear()`. As empirically proven in `test_environment_sanitization_adversarial_isolation_proof`, all parent secrets (`ADVERSARIAL_API_KEY`, `DATABASE_PASSWORD`, etc.) leak directly to child processes at OS launch.
- **Untested angles**:
  - Actual live invocation of Triton / ExLlamaV3 on GPU hardware (marked offline/deterministic per instructions).

## Loaded Skills
- **Source**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md`
- **Local copy**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_2\project-friday-ops_SKILL.md`
- **Core methodology**: Operational runbook for Project Friday testing, piped test logging, and multi-stack supervisor verification.

## Key Decisions Made
- Implemented and executed empirical stress test suite `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs`.
- Proved empirically that `Command::envs` without `cmd.env_clear()` leaks parent environment variables to spawned child processes.
- Verified Job Object concurrency, kill-on-close, loopback proxy bypass, and zero orphaned processes.
- Verdict rendered: `REQUEST_CHANGES` due to missing `cmd.env_clear()` in `spawn_core` and `spawn_tabby`.

## Artifact Index
- `handoff.md` — Final empirical challenge report and verdict.
- `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs` — Empirical challenger stress test harness.
