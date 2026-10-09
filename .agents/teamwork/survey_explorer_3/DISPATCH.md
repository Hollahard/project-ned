# Dispatch — Survey Explorer 3 (Memory, Vector DB & Process Containment)

## Identity
- Archetype: teamwork_preview_explorer
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## Objective
Investigate the technical implementation landscape and status for Requirements R3 and R4:
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (section `## 2026-10-09T13:42:19Z`)
2. Investigate Core Memory & Vector Database Foundation:
   - What SQLite / sqlite-vec structures, modules, migrations, or dependencies exist in the repository?
   - How are vector embeddings, retrieval, eviction, and reconciliation currently handled or planned?
   - How are async database connections managed, and where are potential SQLite thread pool or pytest subshell hanging issues?
3. Investigate Process Guardian & Windows Job Object Security Containment:
   - What Job Object implementations exist (Rust Tauri supervisor, Python ProcessGuardian, etc.)?
   - Where are `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, environment sanitization (PATH, TEMP, SYSTEMROOT whitelist), and secret stripping implemented?
   - How are one-shot HMAC-SHA256 tokens minted and bound to Win32 window handles (HWND)?
   - Where are credentials exposed, and how to verify zero leakage to WebView2 console logs, URLs, or renderer events?
4. Investigate baseline dirty file hashes in `preexisting-dirty-file-hashes.json`:
   - What files are listed, what are their current hashes, and what invariants must be maintained?

## Scope Boundaries
- Read-only investigation. DO NOT modify any code or test files.
- Deliver your findings in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\handoff.md`.
- Send a completion message back to parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d when done.

## 2026-10-09T13:49:55Z
You are Survey Explorer 3 for Project Ned native desktop integration (Memory, Vector DB & Process Containment).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).

Read and analyze:
1. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read section ## 2026-10-09T13:42:19Z first!)
2. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md
3. c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\DISPATCH.md

Your mission:
Investigate requirements R3 and R4 at the code and architectural level:
- Core Memory & Vector Database Foundation: locate existing memory modules, SQLite / sqlite-vec implementations or fixtures, embedding interfaces, retrieval/eviction/reconciliation boundaries, and async database connection management. Check for pytest subshell hanging / aiosqlite teardown patterns.
- Process Guardian & Windows Job Object Security Containment: locate Job Object implementations (in Rust supervisor or Python), JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, child environment sanitization (PATH, TEMP, SYSTEMROOT whitelist), and parent secret stripping.
- Credential isolation: investigate HMAC-SHA256 one-shot token minting, binding to Win32 HWND, and checks ensuring zero leakage to WebView2 URLs or renderer events.
- preexisting-dirty-file-hashes.json: locate this file, inspect its contents and the matching status of files in the workspace.

Deliver your report in: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_3\handoff.md
When done, notify your parent using send_message with recipient 635b9360-b27f-4ffc-82d0-46001e560e8d.
