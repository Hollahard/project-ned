# Dispatch — Worker M1 (Candidate Socket Promotion & Client Typecheck Resolution)

## Identity
- Archetype: teamwork_preview_worker
- Working Directory: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1`
- Parent: orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d)

## MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Context and Inputs to Read FIRST
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (MANDATORY: read section `## 2026-10-09T13:42:19Z` first!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Strict workspace rules: always route tests `cmd.exe /c "..." > log.txt 2>&1`, inspect via view_file, then delete)
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_miner_1\handoff.md` (Specification blueprint)
5. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\survey_explorer_2\handoff.md` (Transport, TS2367, and Tungstenite blueprint)

## Exclusive Write Ownership
You have exclusive write ownership of:
- `hermes-native/apps/desktop-ui/scripts/typecheck.mjs`
- `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`
- `hermes-native/services/owned-ws/tests/input_progress.rs`
- `hermes-native/services/owned-ws/tests/test_vendor_integrity.py`
- `hermes-native/services/owned-ws/vendor-patch-receipt.json`
- `hermes-native/services/owned-ws/vendor-progress-patch.json`
- `hermes-native/services/owned-ws/vendor-progress.diff`
- `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/frame/mod.rs`
- `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/mod.rs`
- `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/progress.rs`
- `hermes-native/services/owned-ws/verify_vendor.py`

DO NOT touch any other files outside your exclusive ownership.

## Objectives
1. **Unpack & Promote Candidate Socket Actor**:
   - Extract/promote the candidate files from `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` (matching manifest `socket-candidates-20261008.json`) into the worktree.
   - Note: The candidate files are also pre-staged in `G:\Project_Ned\.soak_workspace\hermes-native-client-stage` and `hermes-ws-progress-stage`.
2. **Fix TypeScript TS2367 in `native-gateway-socket.ts`**:
   - In `#start()`, replace narrowed comparisons like `this.#state === this.CLOSING` with dynamic property access: `this.readyState === this.CLOSING`. Ensure strict TypeScript compilation passes with zero errors.
   - Fix the peer-close retirement defect at line 202–206: remote close frame observation must NOT set `this.#nativeRetired = true` prematurely. Actor retirement must be certified only when host retirement receipt is received via `#retireHost()`.
   - Ensure reserved terminal delivery preserves preceding message order from `#incoming` before firing `CloseEvent`.
3. **Reconstruct Vendored Tungstenite 0.30.0**:
   - Verify that all 28 vendor files under `hermes-progress-2` receipt are reconstructed with verified SHA-256 hashes and correct LF/CRLF line endings (22 LF upstream, 3 CRLF log-patched, 2 LF progress-patched, 1 LF added `progress.rs`).
   - Run `python hermes-native/services/owned-ws/verify_vendor.py` and ensure it exits 0 with `INFO Vendor source receipt verified (28 files).`
4. **Enforce Parser Progress Safety**:
   - Verify that fatal protocol errors set the sticky `failed` flag so subsequent observations return errors and never produce valid application state.
   - Verify that peer close does not self-certify actor retirement.

## Verification Step
Following GEMINI.md (pipe output to temp log files and inspect via view_file, then delete):
1. Test typecheck:
   `cmd.exe /c "node G:\Personal_Assistant\hermes\hermes-agent\node_modules\typescript\bin\tsc hermes-native/apps/desktop-ui/src/native-gateway-socket.ts --noEmit --strict --target ES2023 --lib ES2023,DOM > tsc_run.txt 2>&1"`
2. Test vendor verifier:
   `cmd.exe /c ".\.venv\Scripts\python.exe hermes-native/services/owned-ws/verify_vendor.py > vendor_run.txt 2>&1"`
3. Test Python vendor tamper suite:
   `cmd.exe /c ".\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > pytest_vendor.txt 2>&1"`
4. Test Rust parser progress & owned-ws:
   `cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1 > cargo_ws.txt 2>&1"`

Deliver your results in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1\handoff.md`.
Notify parent via `send_message` with recipient `635b9360-b27f-4ffc-82d0-46001e560e8d` when complete.
