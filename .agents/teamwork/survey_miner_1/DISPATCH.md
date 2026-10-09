# Dispatch — Survey Spec Miner 1

## Identity
- Archetype: teamwork_preview_spec_miner
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective
Thoroughly extract and document all specifications, acceptance criteria, invariants, hashes, constraints, and contracts from:
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (specifically section `## 2026-10-09T13:42:19Z`)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\docs\hermes-native-desktop\` (and all documentation therein)
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\docs\hermes-native-desktop\implementation-evidence\socket-candidates-20261008.json`
5. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\preexisting-dirty-file-hashes.json` (if present, or search for it across the repo)

## Scope Boundaries
- Read-only investigation. DO NOT modify any production source code or test files.
- Deliver your findings in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1\handoff.md`.
- Include a comprehensive inventory of all requirements R1, R2, R3, R4, expected file paths, integrity hashes, and verification commands.
- Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.

## 2026-10-09T13:49:55Z
From: 635b9360-b27f-4ffc-82d0-46001e560e8d
Content:
You are the Specification Miner for Project Ned native desktop integration survey.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1\DISPATCH.md
4. docs/hermes-native-desktop/ and all documentation, architecture guides, and implementation evidence therein.
5. docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.json
6. preexisting-dirty-file-hashes.json (locate in repo)

Your mission:
Extract and catalog all specifications, acceptance criteria, thresholds, invariants, contracts, candidate manifest entries, and expected file structures for Requirements R1, R2, R3, and R4.
Deliver your report in: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1\handoff.md
When done, notify your parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d.
