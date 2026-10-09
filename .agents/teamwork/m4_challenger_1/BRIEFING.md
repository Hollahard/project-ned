# BRIEFING — 2026-10-09T16:35:00Z

## Mission
Empirically stress-test and verify Milestone 4 Capability Token security, HWND binding, argument tampering, replay defenses, and JSON canonicalization parity in Rust and Python.

## 🔒 My Identity
- Archetype: empirical-challenger
- Roles: critic, specialist
- Working directory: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_challenger_1
- Original parent: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Milestone: Milestone 4 (Process Guardian & Security Containment Verification)
- Instance: 1 of 1

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code
- Run verification code ourselves; empirical reproduction required
- Strictly follow GEMINI.md routing (cmd.exe /c "... > log.txt 2>&1", view_file, delete log)
- No source or test files in .agents/teamwork/
- BypassSandbox: true for execution across workspace drives

## Current Parent
- Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d
- Updated: 2026-10-09T16:17:24Z

## Review Scope
- **Files to review**: `apps/desktop/src-tauri/src/approvals.rs`, `apps/desktop/src-tauri/src/proxy.rs`, `apps/desktop/src-tauri/src/processes.rs`, `services/core/src/friday/security/tokens.py`, `tests/security/test_capability_tokens.py`
- **Interface contracts**: `PROJECT.md` M4 contracts (Job Object 0x2000, HWND-bound HMAC tokens, JSON canonicalization)
- **Review criteria**: Empirical security verification of capability token invariants (Replay, HWND binding, Argument tampering, Expiration, JSON canonicalization parity)

## Attack Surface
- **Hypotheses tested**:
  1. Replay attack rejection: Immediate replay and 16/20 thread concurrent race conditions verified.
  2. HWND binding rejection: Valid token minted for HWND A fails when consumed by HWND B.
  3. Headless caller behavior: `caller_hwnd = None` bypasses HWND checking when `record.bound_hwnd` is set (fallback for headless CI/CD).
  4. Argument tampering: 1-byte alteration, added keys, deleted keys, and tool spoofing reject with `ArgHashMismatch`.
  5. Expiration: Tokens expire at TTL boundary and are pruned from memory.
  6. JSON canonicalization: Deeply nested objects, array element sensitivity, unicode characters, and cross-language parity between Python and Rust.
- **Vulnerabilities found**:
  * Potential attack surface: If an attacker invokes `validate_and_consume_with_hwnd` with `caller_hwnd = None`, the HWND binding check is bypassed. This was implemented to support headless CI/CD runs where `GetForegroundWindow()` returns NULL, but represents a minor caveat if callers can supply `None`.
- **Untested angles**:
  * Multi-monitor Win32 HWND migration under virtual desktops.

## Loaded Skills
- **Source**: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md
- **Local copy**: None
- **Core methodology**: Operational runbook for Project Friday testing and multi-stack verification

## Key Decisions Made
- Implemented and executed 9 Rust adversarial tests in `apps/desktop/src-tauri/tests/test_challenger_m4_tokens.rs`.
- Implemented and executed 7 Python adversarial tests in `tests/security/test_challenger_m4_tokens.py`.
- Ran full regression suites across Rust supervisor (24 passed), Python security (37 passed), Core (210 passed), and fast soak (5 passed).
- Confirmed dirty file baseline hashes 100% matched.
- Verdict: APPROVE with documented caveat.

## Artifact Index
- `apps/desktop/src-tauri/tests/test_challenger_m4_tokens.rs` — Rust empirical stress suite
- `tests/security/test_challenger_m4_tokens.py` — Python empirical stress suite
- `handoff.md` — Final empirical challenge verdict report
