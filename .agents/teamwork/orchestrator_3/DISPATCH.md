# Dispatch: Project Orchestrator (orchestrator_3)

## Mission
Resume Project Ned native desktop integration from checkpoint commit 2afa8ea on branch codex/hermes-native-foundation. Promote unfinished socket actor candidates, fix client TypeScript typechecking, verify owned WebSocket transports, and implement the local vector database / memory foundation with strict Windows process isolation.

## Working Directory
`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3`

## Authoritative User Request
Refer to `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (specifically header `## 2026-10-09T13:42:19Z`).

## Key Workspace Rules & Constraints
1. **Adhere to GEMINI.md**:
   - Always route tests to output files: `cmd.exe /c "..." > log.txt 2>&1` and inspect via view_file. Delete log afterwards.
   - Quote paths and parenthesized strings in PowerShell.
   - Use `BypassSandbox: true` where necessary for reliable execution across drives.
   - Zero orphaned processes: child processes (Core and TabbyAPI) inside Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
   - Environment sanitization: whitelist only `PATH`, `TEMP`, `SYSTEMROOT`.
   - Sidecar isolation: keep TabbyAPI in its isolated `.venv`.
   - Async database fixtures: explicitly await `db_manager.close()` during teardown to avoid hanging SQLite threads.
   - Mock tools inheriting from `Tool` must define `parameters_schema`.
2. **Requirements**:
   - R1: Promote candidate socket actor from `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` & `socket-candidates-20261008.json`. Fix TypeScript TS2367 in `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`. Ensure Tungstenite 28 output files reconstruct cleanly. Enforce parser progress safety.
   - R2: Run and pass 19 owned-ws tests, 7 owned-http tests, 8 parser progress tests, 8 Python vendor-tamper tests against frozen vendor sources. Expand and pass `hermes-native/scripts/Verify-Foundation.ps1`.
   - R3: Core memory & sqlite-vec foundation. Teardown safety.
   - R4: Process guardian & Windows Job Object containment. Zero bearer token leakage. Baseline dirty files match `preexisting-dirty-file-hashes.json`.


## 2026-10-09T13:44:55Z
You are the Project Orchestrator (orchestrator_3) for Project Ned native desktop integration.
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3
Your task is to orchestrate and implement all requirements specified in:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (under section ## 2026-10-09T13:42:19Z).

See dispatch details at:
c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\DISPATCH.md

Core Requirements:
- R1: Candidate Socket Promotion & Client Typecheck Resolution (promote candidates from docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip & manifest, fix TS2367 in hermes-native/apps/desktop-ui/src/native-gateway-socket.ts, reconstruct Tungstenite files, parser progress safety).
- R2: Owned WebSocket & Transport Foundation Verification (run and pass 19 owned-ws, 7 owned-http, 8 parser progress, 8 Python vendor-tamper tests, expand and pass hermes-native/scripts/Verify-Foundation.ps1).
- R3: Core Memory & Vector Database Foundation (sqlite-vec / SQLite storage, embedding strategies, clean async db teardown).
- R4: Process Guardian & Windows Job Object Security Containment (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, environment sanitization, isolated HMAC tokens, zero token leakage, baseline dirty file preservation per preexisting-dirty-file-hashes.json).

Maintain your plan.md, progress.md, and BRIEFING.md in your working directory.
Adhere strictly to GEMINI.md workspace rules.
When complete, provide a full handoff and notify the Sentinel.
