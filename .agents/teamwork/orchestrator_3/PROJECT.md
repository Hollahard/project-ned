# Project: Project Ned Native Desktop Integration

## Architecture
Project Ned native desktop integration bridges the Rust Tauri native desktop shell (`hermes-native/apps/desktop-shell`, `apps/desktop/src-tauri`) with local python Core services (`services/core/`) and high-performance native transports (`hermes-native/services/owned-ws`, `hermes-native/services/owned-http`).

### Key Subsystems & Boundaries
1. **Transport Layer (`hermes-native/services/owned-ws`, `owned-http`)**:
   - Vendored Tungstenite 0.30.0 with `hermes-progress-2` patch providing monotonic wire offset tracking (`InputProgress`).
   - Sticky error latching on fatal protocol errors.
   - Preceding message draining prior to terminal CloseEvent delivery.
2. **Client Gateway Socket (`hermes-native/apps/desktop-ui`)**:
   - Native gateway socket client (`native-gateway-socket.ts`) with dynamic state resolution avoiding TS2367 type narrowing errors.
   - Strict separation of peer-close observation from supervisor actor retirement.
3. **Core Memory & Storage Subsystem (`services/core/src/friday/memory/`, `storage/`)**:
   - Profile-scoped SQLite in WAL mode with `vec0` vector tables (`sqlite-vec`).
   - Local offline CPU embeddings with zero external cloud dependencies.
   - Immediate canonical deletion/rewind invalidation (F02) and durable outbox reconciliation (F03).
   - Strict async database fixture teardown awaiting `db_manager.close()` preventing Windows thread pool hangs.
4. **Security & Process Containment (`apps/desktop/src-tauri/src/`, `services/core/src/friday/security/`)**:
   - Windows Job Object containment with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` and breakaway prohibition.
   - Unrestricted child worker concurrency (`ActiveProcessLimit == 0`).
   - Child environment sanitization whitelisting only system variables and stripping secrets.
   - Single-use HMAC-SHA256 capability tokens bound to Win32 HWND.
   - Reverse proxy token isolation keeping bearer tokens in supervisor memory and `.no_proxy()` loopback bypassing.
   - Strict byte-identical preservation of baseline dirty files.

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Candidate Archive Unpacking | Extract 12 candidate files from `socket-candidates-20261008.zip` matching preimages | M1 | Survey Miner 1 / Explorer 2 |
| 2 | TypeScript TS2367 Resolution | Fix state narrowing comparison in `native-gateway-socket.ts` | M1 | Survey Miner 1 / Explorer 2 |
| 3 | Peer-Close Host Retirement Invariant | Separate remote close observation from actor retirement | M1 | Survey Explorer 2 |
| 4 | Vendored Tungstenite 0.30.0 Pack | Reconstruct 28 vendor files under `hermes-progress-2` receipt with LF/CRLF integrity | M1 | Survey Miner 1 / Explorer 2 |
| 5 | InputProgress Monotonic Tracking | Expose wire offsets (`buffered_wire_start`, `pending_frame_start`, etc.) | M1 | Survey Miner 1 / Explorer 2 |
| 6 | Post-Error State Invalidation | Sticky `FrameProgress.failed` latch on protocol errors | M1 | Survey Miner 1 / Explorer 2 |
| 7 | Reserved Terminal Delivery Order | Drain and dispatch queued messages ahead of terminal CloseEvent | M1 | Survey Miner 1 / Explorer 2 |
| 8 | 19 Owned-WS Integration Tests | Pass 10 native_ws, 1 lib, 8 input_progress tests | M2 | Survey Explorer 2 |
| 9 | 7 Owned-HTTP Integration Tests | Pass 5 native_http, 2 lib/ownership tests | M2 | Survey Explorer 2 |
| 10 | 8 Python Vendor Tamper Tests | Pass all 8 pytest integrity checks in `test_vendor_integrity.py` | M2 | Survey Explorer 2 |
| 11 | Verify-Foundation.ps1 4-Gate Expansion | Expand PowerShell runner with vendor, vendor-tests, lint, format gates | M2 | Survey Explorer 2 |
| 12 | Truthful Backend-Unavailable Reporting | UI truthfully reports backend unavailable until gateway qualifies | M2 | Survey Miner 1 / Explorer 2 |
| 13 | SQLite & sqlite-vec Schema | Profile-scoped WAL SQLite with `vec0` tables | M3 | Survey Miner 1 / Explorer 3 |
| 14 | Local CPU Embedding Pipeline | Offline vector generation without cloud dependencies | M3 | Survey Miner 1 / Explorer 3 |
| 15 | F02 Canonical Validity on Recall | Exclude absent, deleted, or rewound items at retrieval boundary | M3 | Survey Miner 1 / Explorer 3 |
| 16 | F03 Outbox & Reconciliation | Idempotent reconciliation cursor catching up unindexed commits | M3 | Survey Miner 1 / Explorer 3 |
| 17 | Untrusted Memory Excerpt Fencing | Enforce `MEMORY_OUTPUT_FENCE_PREFIX` to prevent prompt injection | M3 | Survey Miner 1 / Explorer 3 |
| 18 | Async DB Teardown Safety | Async yield fixtures explicitly await `db_manager.close()` | M3 | Survey Miner 1 / Explorer 3 |
| 19 | Windows Job Object Containment | Enforce `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` and deny breakaway | M4 | Survey Miner 1 / Explorer 3 |
| 20 | Child Worker Concurrency | Keep `ActiveProcessLimit == 0` for multi-process concurrency | M4 | Survey Explorer 3 |
| 21 | Child Environment Sanitization | Whitelist only explicit OS vars and strip parent secrets | M4 | Survey Miner 1 / Explorer 3 |
| 22 | HMAC-SHA256 Tokens with HWND Binding | 120s TTL, single-use, canonical JSON hashing, bound to caller HWND | M4 | Survey Miner 1 / Explorer 3 |
| 23 | Reverse Proxy Isolation & Loopback Fix | Zero bearer tokens to WebView2; add `.no_proxy()` to reqwest loopback | M4 | Survey Explorer 3 |
| 24 | Baseline Dirty File Preservation | Maintain 100% byte-identical hashes per `preexisting-dirty-file-hashes.json` | M4 | Survey Miner 1 / Explorer 3 |
| 25 | Full Dual-Track Acceptance Verification | 100% pass across all 4 tiers, regression suites, and forensic audit | M5 | Master Plan |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| **M1** | **Candidate Socket Promotion & Client Typecheck Resolution** | Promote 12 candidate files from zip; fix TS2367 in `native-gateway-socket.ts`; fix peer-close retirement bug; reconstruct 28 Tungstenite files; verify `InputProgress` safety | None | **DONE** |
| **M2** | **Owned WebSocket & Transport Foundation Verification** | Run and pass 19 owned-ws tests, 7 owned-http tests, 8 progress tests, 8 tamper tests; expand `Verify-Foundation.ps1` with 4 vendor gates; verify foundation | M1 | **DONE** |
| **M3** | **Core Memory & Vector Database Foundation** | Implement SQLite / sqlite-vec schema, local CPU embeddings, F02 canonical deletion/rewind invalidation, F03 outbox reconciliation, async teardown safety | None | **DONE** |
| **M4** | **Process Guardian & Security Containment Verification** | Verify Job Object 0x2000 containment, child concurrency, environment sanitization, HMAC tokens bound to HWND, `.no_proxy()` loopback fix, dirty file hash preservation | None | **DONE** |
| **M5** | **Final Integration, Acceptance Verification & Audit** | Full E2E multi-suite qualification (all unit, integration, transport, and security suites pass 100%), Forensic Integrity Audit, and Sentinel handoff | M1, M2, M3, M4 | **DONE** |

---

## Interface Contracts
### Client Socket ↔ Native Transport
- `NativeGatewaySocket.readyState`: `0` (CONNECTING), `1` (OPEN), `2` (CLOSING), `3` (CLOSED).
- `NativeGatewaySocket.#start()`: Evaluates dynamic readiness via `this.readyState === this.CLOSING` to avoid literal narrowing across async calls.
- Remote Close: Dispatches preceding queued messages in `#incoming` before firing `CloseEvent`. Sets `this.#remoteClose`, but leaves `this.#nativeRetired = false` until host `retire` confirmation.

### Transport ↔ Parser Progress (`InputProgress`)
- `InputProgress`: Exposes monotonic `buffered_wire_start`, `buffered_wire_end`, `pending_frame_start`, `pending_frame_end`, `fragmented_data_start`.
- Sticky Error Latch: `FrameProgress.failed = true` permanently invalidates parser on fatal protocol error.

### Core Memory ↔ Storage
- Database: WAL mode SQLite with `vec0` virtual table for vector embeddings.
- Retrieval Boundary: Canonical check against `sessions`/`messages` must fail-closed if record is deleted or rewound.
- Memory Excerpt: Output fenced with `[TOOL RESULT: MEMORY SEARCH DATA ONLY...]`.
- Fixture Teardown: `await db_manager.close()` during fixture cleanup.

### Supervisor ↔ Process Guardian
- Job Object Limit: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`. Breakaway denied.
- ActiveProcessLimit: `0` (unrestricted child worker concurrency).
- Environment Whitelist: `PATH`, `TEMP`, `TMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`.
- Capability Tokens: HMAC-SHA256, 120s TTL, single-use, canonical JSON args (`sort_keys=True`), bound to caller Win32 `HWND`.
- Loopback Proxy: `reqwest::Client::builder().no_proxy()`.

---

## Code Layout
- `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts` (M1 write ownership)
- `hermes-native/apps/desktop-ui/scripts/typecheck.mjs` (M1 write ownership)
- `hermes-native/services/owned-ws/` (M1/M2 write ownership: vendor files, diffs, receipts, verify_vendor.py, input_progress.rs, test_vendor_integrity.py)
- `hermes-native/scripts/Verify-Foundation.ps1` (M2 write ownership)
- `services/core/src/friday/memory/` (M3 write ownership)
- `services/core/src/friday/storage/` (M3 write ownership)
- `services/core/tests/test_memory_*.py` (M3 write ownership)
- `apps/desktop/src-tauri/src/approvals.rs` (M4 write ownership)
- `apps/desktop/src-tauri/src/processes.rs` (M4 write ownership)
- `apps/desktop/src-tauri/src/proxy.rs` (M4 write ownership)
