# Survey Explorer 3 Handoff Report — Memory, Vector DB & Process Containment (R3 & R4)

**Date**: 2026-10-09T14:08:00Z  
**Author**: Survey Explorer 3 (`teamwork_preview_explorer`)  
**Workspace**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Scope**: Requirements R3 (Memory & Vector DB) and R4 (Process Guardian & Security Containment)

---

## 1. Observation

### 1.1 Baseline Dirty File Hashes (`preexisting-dirty-file-hashes.json`)
1. **Location Found**: `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`.
2. **Contents Verified**:
   ```json
   [
     {
       "Path": "G:\\Project_Ned\\apps\\desktop\\src-tauri\\src\\lib.rs",
       "Hash": "5F779262B46E2AF882E28D3C43547840CCA16CAF7E64EB2CB907DFC2F46507A9"
     },
     {
       "Path": "G:\\Project_Ned\\apps\\desktop\\src-tauri\\src\\proxy.rs",
       "Hash": "4BA5FDDA63C12F7275F81506D01B535A154259D2C0F0A2A132C377BEE505EDE3"
     },
     {
       "Path": "G:\\Project_Ned\\apps\\desktop\\src-tauri\\tauri.conf.json",
       "Hash": "1843E0D02AB9D344AACAB0B9292FE1E2AD1D98D700D77659612F52391D7EEED0"
     },
     {
       "Path": "G:\\Project_Ned\\apps\\desktop\\vite.config.ts",
       "Hash": "D4F0ED4FE30358370157528C73510C8C1BF7644A8775345CEC22D90DBEB8B0AF"
     }
   ]
   ```
3. **Status in `G:\Project_Ned`**:
   - `apps/desktop/src-tauri/src/lib.rs` -> SHA256: `5F779262B46E2AF882E28D3C43547840CCA16CAF7E64EB2CB907DFC2F46507A9` (100% MATCH)
   - `apps/desktop/src-tauri/src/proxy.rs` -> SHA256: `4BA5FDDA63C12F7275F81506D01B535A154259D2C0F0A2A132C377BEE505EDE3` (100% MATCH)
   - `apps/desktop/src-tauri/tauri.conf.json` -> SHA256: `1843E0D02AB9D344AACAB0B9292FE1E2AD1D98D700D77659612F52391D7EEED0` (100% MATCH)
   - `apps/desktop/vite.config.ts` -> SHA256: `D4F0ED4FE30358370157528C73510C8C1BF7644A8775345CEC22D90DBEB8B0AF` (100% MATCH)
4. **Status in Current Worktree (`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`)**:
   - `git status --porcelain` shows a clean tree (only untracked `.agents/teamwork/` metadata directories).
   - The current worktree is based on checkpoint commit `2afa8ea` (`codex/hermes-native-foundation`), where these 4 files contain committed differences:
     * `lib.rs`: `7CA20BF6C1EA7AAA0D66AA7D4C18A31A18DCADA76AC6BF15874CD943AFD7848F`
     * `proxy.rs`: `D733A0CE110422FBB134A0B56F04E4784EAB437BF5B7725A5972B851549C09D3`
     * `tauri.conf.json`: `6B5A67E60B504A8AB33E7678729EEACB265EFCF10E1F90950C3B2DD45FD1A5E3`
     * `vite.config.ts`: `05B9243F78E3E5A2A432478EE9AF1F63317A93AEC6A7F32208DE536654D29D39`

---

### 1.2 Core Memory & Vector Database (Requirement R3)
1. **Existing Memory Implementation**:
   - Located at `services/core/src/friday/memory/`:
     * `coordinator.py` (lines 22–94): `MemoryCoordinator` orchestrating `WorkingMemory`, `SemanticMemory`, `EpisodicMemory`, and `ProceduralMemory`. Enforces `MEMORY_OUTPUT_FENCE_PREFIX` (lines 14–19) and context budget truncations.
     * `semantic.py` (lines 81–141): `SemanticMemory.search()` executes SQLite FTS5 queries (`semantic_memory_fts`) strictly scoped to `workspace_root`.
     * `episodic.py` (lines 16–54): `EpisodicMemory.search()` executes SQLite FTS5 queries (`messages_fts`) joined with `sessions` on `working_directory = :workspace_root`.
     * `procedural.py` (lines 62–126): `ProceduralMemory.search()` executes SQLite FTS5 queries (`procedural_memory_fts`), with unapproved playbooks suppressing executable steps to prevent unauthorized replay.
     * `working.py` (lines 6–30): Ephemeral per-turn in-memory note list.
2. **Existing Storage & Database Manager**:
   - Located at `services/core/src/friday/storage/db.py`:
     * `DatabaseManager` (lines 161–297): Connects via `aiosqlite.connect(self.db_path)`, enables WAL mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;`).
     * Tables created: `sessions`, `messages`, `events`, `settings`, `model_profiles`, `messages_fts` (virtual fts5), `semantic_memory`, `semantic_memory_fts` (virtual fts5), `procedural_memory`, `procedural_memory_fts` (virtual fts5), and `skills_metadata`.
3. **Vector Database / `sqlite-vec` Gap**:
   - Running `import sqlite_vec` in `.venv` returns: `ModuleNotFoundError: No module named 'sqlite_vec'`.
   - `sqlite-vec` is not listed in `services/core/pyproject.toml` dependencies.
   - Grepping `vec0` across the repository returns 0 occurrences.
   - Architectural specifications in `docs/hermes-native-desktop/ARCHITECTURE.md` (lines 213, 221, 433, 906) and `FEATURE-REVIEW.md` (F02, F03) define the contract:
     * Milestone 3 target: Profile-scoped `vector-memory.db` with pinned `sqlite-vec` extension and CPU embeddings.
     * Hybrid retrieval: Combine FTS5 keyword recall with `vec0` vector KNN/cosine search.
     * F02 Boundary: Immediate canonical delete/rewind invalidation. Recalled vector chunks must verify source validity against canonical tables (`sessions`, `messages`, `semantic_memory`) at recall time; absent, rewound, or soft-deleted records fail-closed and are excluded.
     * F03 Boundary: Outbox decoupling from canonical commits via idempotent source reconciliation with a high-watermark or durable generation counter.
     * Zero external dependencies: Vector generation must use offline CPU embeddings (or lightweight local embeddings), strictly avoiding unmanaged cloud APIs.
4. **Async Database Teardown & Subshell Hang Invariants**:
   - `services/core/tests/` fixtures (`test_memory_tiers.py:15-22`, `test_telemetry.py:40-51`, `test_api.py:13-24`, `test_scheduler_storage.py:19-26`, `test_subagent_storage.py:14-22`, `tests/soak/test_soak_endurance.py:119-128`) all follow the async `yield` pattern awaiting `db_manager.close()`.
   - Executing `.\.venv\Scripts\pytest.exe services/core/tests/ -q` executed 185 tests in 19.30s with 100% pass and 0 subshell hangs.

---

### 1.3 Process Guardian & Windows Job Object Security Containment (Requirement R4)
1. **Supervisor Process Guardian (Rust)**:
   - Located at `apps/desktop/src-tauri/src/processes.rs`:
     * `JobObject::new()` (lines 55–82): Calls `CreateJobObjectW(null(), null())`. Sets `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` with `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`.
     * Concurrency Invariant: Deliberately omits `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, keeping `ActiveProcessLimit == 0` so child concurrency (Core FastAPI and TabbyAPI sidecars) is unrestricted.
     * Assignment: `job_object.assign(&child)` via `AssignProcessToJobObject`.
     * Dropping `JobObject` (lines 160–170) closes the handle, triggering the Windows kernel to unconditionally terminate all child processes.
     * Environment Sanitization (`build_sanitized_env`, lines 174–223): Whitelists only `PATH`, `TEMP`, `TMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`. Strips all parent environment secrets.
2. **Skill Host Process Cage (Python)**:
   - Located at `services/core/src/friday/skills/cage.py` (`WindowsJobCage`):
     * Cages third-party untrusted skills. Intentionally sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS` with `ActiveProcessLimit = 1` and `JOB_OBJECT_UILIMIT_ALL` UI restrictions.
3. **Soak Supervisor Containment (Python)**:
   - Located at `tests/soak/run_8hr_soak.py` (`Win32JobSupervisor`) and verified by `tests/soak/test_adversarial_cli_lifecycle.py`:
     * Tests multi-worker concurrency (5 concurrent `ping.exe` workers), queries active count, closes supervisor, and verifies zero orphaned processes via `tasklist`.
4. **Hermes Native Resource Host (Rust)**:
   - Located at `hermes-native/services/resource-host/src/windows.rs` (`WorkerGroup`):
     * Implements unnamed `CreateJobObjectW` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and captured stdio handles.

---

### 1.4 Credential Isolation & Token Architecture (Requirement R4)
1. **One-Shot Capability Tokens**:
   - Rust: `apps/desktop/src-tauri/src/approvals.rs` (`ApprovalManager`):
     * Mints tokens with HMAC-SHA256: `token_id:tool_name:args_hash:expires_at` using secret key.
     * TTL: 120 seconds.
     * Single-use consumption: `validate_and_consume` tracks consumed tokens in `consumed_tokens: Arc<Mutex<Vec<String>>>`.
     * Arguments canonicalization: `canonicalize_json_value` sorts object keys deterministically to match Python's `sort_keys=True`.
   - Python: `services/core/src/friday/security/tokens.py` (`CapabilityTokenManager`):
     * Mints tokens matching the identical HMAC-SHA256 signature scheme with canonical JSON serialization.
     * Tested in `tests/security/test_capability_tokens.py` (all 6 tests passed).
2. **Win32 Window Handle (HWND) Binding**:
   - In `apps/desktop/src-tauri/src/approvals.rs:100`, `MessageBoxW` currently passes `std::ptr::null_mut()` as the parent `hWnd`.
   - In `hermes-native/apps/desktop-shell/src/control.rs:43-69` and `catalog.rs:92-120`, exact main window HWND binding is enforced via `window.hwnd()` and atomic CAS:
     ```rust
     let hwnd = window.hwnd().map_err(|_| ControlError::unavailable())?.0 as isize;
     self.owner.compare_exchange(0, hwnd, Ordering::AcqRel, Ordering::Acquire)
     ```
   - Requirement R4 demands that native dialogs and capability tokens be bound to the caller's Win32 HWND rather than detached or null handles.
3. **WebView2 Zero Leakage**:
   - `apps/desktop/src-tauri/src/proxy.rs`: `SupervisorProxy` holds `core_bearer_token` and `tabby_admin_key` in Rust supervisor memory only.
   - The WebView2 frontend never sees bearer tokens or admin keys; it interacts strictly through typed Tauri IPC commands in `commands.rs`.
   - `services/core/src/friday/telemetry/tracer.py`: `redact_sensitive_text` and `sanitize_payload` scrub capability tokens, bearer tokens, and API keys from traces and logs (verified by `tests/security/test_security_redteam.py:657`, 30/30 tests passed).
   - `hermes-native/spikes/webview2-guest/src/lib.rs`: Proves WebView2 guest navigation bounds, storage partitioning, and absence of privileged bridge injection (`hermes_bridge`, `tauri_bridge`, `ipc_bridge` all `undefined`).
4. **Supervisor Proxy Direct IP Access Issue**:
   - Running `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml` executed:
     * `first_launch::tests`: 5/5 passed.
     * `test_job_object_limits_permit_concurrency_and_kill_on_close`: PASSED.
     * `test_supervisor_repeated_operations_no_handle_or_thread_leak`: FAILED with:
       ```
       Warmup create_session failed: CoreError { status: 400, body: "Direct IP access is not allowed\n" }
       ```
   - Root cause: `apps/desktop/src-tauri/src/proxy.rs` line 132 instantiates `reqwest::Client::builder()` without `.no_proxy()`. In Windows environments with corporate/system proxy settings, loopback requests to `http://127.0.0.1:<port>` are routed through the proxy, which rejects direct IP access with HTTP 400.

---

## 2. Logic Chain

1. **Preexisting Hashes**:
   - Directly observed `preexisting-dirty-file-hashes.json` in `G:\Project_Ned\.soak_workspace\`.
   - Verified that the 4 files in `G:\Project_Ned` match the hashes 100%.
   - In `C:\Users\Ghols\...` worktree, these files represent the committed `2afa8ea` state. Therefore, any work in `G:` must preserve these 4 hashes, and work in `C:` must not introduce dirty drift to application code.

2. **Memory Subsystem (R3)**:
   - Observed that `services/core/src/friday/memory/` contains a fully functional 4-tier FTS5 SQLite implementation (`coordinator.py`, `semantic.py`, `episodic.py`, `procedural.py`, `working.py`).
   - Observed that neither `sqlite-vec` nor vector embeddings currently exist in code.
   - Traced architecture requirements in `docs/hermes-native-desktop/ARCHITECTURE.md` (ADR05) and `FEATURE-REVIEW.md` (F02, F03): vector search must be implemented as a local `sqlite-vec` extension (`vec0`), using CPU embeddings, with a fail-closed canonical source check at retrieval time to ensure deleted or rewound messages are never resurrected.
   - Verified that `services/core/tests/` fixtures follow strict async teardown (`await db_manager.close()`), running 185 tests in 19.30s without hangs.

3. **Process Containment & Credential Isolation (R4)**:
   - Observed `JobObject` in `apps/desktop/src-tauri/src/processes.rs` correctly applies `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` and omits `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, satisfying worker concurrency while guaranteeing zero orphans upon parent exit.
   - Observed `build_sanitized_env` whitelist in `processes.rs` strictly stripping parent environment secrets.
   - Observed capability tokens using HMAC-SHA256 with 120s TTL and canonical argument hashing.
   - Observed that `approvals.rs` needs HWND parameterization for `MessageBoxW` and token payload to satisfy the HWND binding invariant.
   - Discovered that `reqwest::Client` in `proxy.rs` requires `.no_proxy()` to prevent system proxy interception of `127.0.0.1` traffic.

---

## 3. Caveats

1. `sqlite-vec` is an external C/Rust SQLite extension. In offline development environments (like this machine where crates.io and external network downloads are restricted), the extension binary or wheel must be pre-vendored or statically built.
2. In `apps/desktop/src-tauri`, cargo builds require `--offline` because network access to crates.io is blocked by root certificate authority (`SEC_E_UNTRUSTED_ROOT`).
3. While all 185 Python core tests and 30 security tests pass, the Rust supervisor integration test currently trips on the missing `.no_proxy()` configuration in `reqwest::Client`.

---

## 4. Conclusion

- **R3 Status**: Core 4-tier memory foundation is stable and passes all tests. Vector memory (`sqlite-vec`) is completely unbuilt and must be constructed in Milestone 3: adding `sqlite-vec` / `vec0` tables, local CPU embedding provider, canonical deletion/rewind reconciliation (F02), and outbox durability (F03).
- **R4 Status**: Windows Job Object process containment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), active process concurrency, and environment sanitization are fully verified in both Rust (`processes.rs`) and Python (`run_8hr_soak.py`, `test_adversarial_cli_lifecycle.py`).
- **Credential Isolation Status**: Reverse proxy design ensures zero bearer tokens leak to WebView2. Capability token minting via HMAC-SHA256 is verified. HWND binding needs to be explicitly wired into `approvals.rs`. In `proxy.rs`, `.no_proxy()` must be added to `reqwest::Client::builder()`.
- **Preexisting Dirty Files**: Located in `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json` with 100% hash match in `G:\Project_Ned` and clean git state in current worktree `C:\...`.

---

## 5. Verification Method

1. **Verify Baseline Hashes**:
   ```pwsh
   .\.venv\Scripts\python.exe -c "import hashlib, json, pathlib; [print(f, hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest().upper()) for f in ['G:/Project_Ned/apps/desktop/src-tauri/src/lib.rs', 'G:/Project_Ned/apps/desktop/src-tauri/src/proxy.rs', 'G:/Project_Ned/apps/desktop/src-tauri/tauri.conf.json', 'G:/Project_Ned/apps/desktop/vite.config.ts']]"
   ```
2. **Verify Core Memory Tests & Async Teardown**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/test_memory_tiers.py -v > pytest_mem.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -q > pytest_core.log 2>&1"
   ```
   (Verify 185 passed, 0 hangs, delete logs).
3. **Verify Security & Capability Token Tests**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > pytest_sec.log 2>&1"
   ```
   (Verify 30 passed, delete log).
4. **Verify Rust Job Object Invariants**:
   ```cmd
   cmd.exe /c "cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants test_job_object_limits_permit_concurrency_and_kill_on_close > cargo_job.log 2>&1"
   ```
   (Verify 1 passed, delete log).
