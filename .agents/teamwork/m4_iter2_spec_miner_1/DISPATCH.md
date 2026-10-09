# DISPATCH — m4_iter2_spec_miner_1

## Task Assignment
Milestone 4 Iteration 2: Specification & Contract Mining on Process Environment Sanitization.

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1`

## Mandatory Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (Read section `## 2026-10-09T13:42:19Z`!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Read Rule 2: Process Guardian & Sidecar Invariants!)
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\docs\hermes-native-desktop\` architecture documents

## Investigation Scope
- Mine the exact specifications and invariants for Process Guardian environment sanitization:
  * Section from `GEMINI.md`: "Environment Sanitization: Never copy std::env::vars() or os.environ wholesale to child processes. Strip parent secrets and pass only explicit whitelist variables (PATH, TEMP, SYSTEMROOT) and process tokens."
  * Feature 21 from `PROJECT.md`: "Child Environment Sanitization: Whitelist only explicit OS vars and strip parent secrets."
- Document how Rust's `std::process::Command::env_clear` interacts with Windows process creation (`CreateProcessW` environment block parameter).
- Extract acceptance criteria and verification commands to ensure the fix meets all project invariants. DO NOT implement changes yourself.

## Output
Write your analysis and mined specification report to:
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1\handoff.md`
Notify parent with `send_message` (Recipient: `635b9360-b27f-4ffc-82d0-46001e560e8d`) when complete.

## 2026-10-09T16:34:36Z
You are Spec Miner 1 for Milestone 4 Iteration 2 (Process Sanitization Invariants).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md (Rule 2: Process Guardian & Sidecar Invariants!)
4. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1\DISPATCH.md

Mission:
Mine and document all formal requirements, specifications, and test contracts regarding process environment sanitization:
- Contrast Windows Win32 CreateProcessW environment block handling with Rust std::process::Command env inheritance.
- Document exact whitelist variables required by Windows subsystem for stable Python runtime execution.
- Define the exact pass/fail acceptance criteria and verification commands for Milestone 4 Iteration 2.
- Note: DO NOT implement changes yourself. Only document specifications and requirements.

Deliver your report in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1\handoff.md
Notify parent via send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.
