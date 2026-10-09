# Handoff Report — Survey Explorer 2
**Scope**: Project Ned Native Desktop Integration: Requirements R1 & R2 (Transport, Sockets & Vendor Integrity)  
**Date**: 2026-10-09  
**Investigator**: survey_explorer_2 (teamwork_preview_explorer)  
**Recipient**: orchestrator_3 (`635b9360-b27f-4ffc-82d0-46001e560e8d`)

---

## 1. Observation

### 1.1 Candidate Archive & Manifest Inspection
- **Manifest File**: `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.json`
- **Archive File**: `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip`
- **Archive SHA256**: `4456aad2639be93f67aaa18840c3e8e4152b2ab6eb9fd7210cdc55544c168a3e` (verified via `Get-FileHash docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip -Algorithm SHA256`).
- **Archive Member List & Preimage Status**:
  The archive contains exactly 12 files. Comparison against the current working tree (`c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned` at checkpoint commit `2afa8ea`, based on `2ffddc6`) reveals that 6 files currently exist with matching `base_sha256`, and 6 files are currently missing:

  | File Path | Bytes | Candidate SHA256 (`socket-candidates-20261008.zip`) | Base SHA256 | Current Workspace Status | Promotion Action |
  |---|---|---|---|---|---|
  | `hermes-native/apps/desktop-ui/scripts/typecheck.mjs` | 2,433 | `d68011aec53992db0163f2473d571e762ef5ca6fdf85407f2cbbc368e8fc2d41` | `69ad05b4ada479d7e6097022646ccf5a08a0fc09890ef1f847c5352b2b67d2c2` | Exists (`base_sha256` matches) | Overwrite with candidate |
  | `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts` | 18,211 | `104fc8c6168722cd7fb0527e02ab456275a487c4c90db3d24ccac757c765db34` | `null` | Missing | Add candidate (with TS fix) |
  | `hermes-native/scripts/Verify-Foundation.ps1` | 15,293 | `50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230` | `09c256f036c75253f71167d5f8219e71c6b2fc368b3e072949a8a2cb6550aef0` | Exists (`base_sha256` matches) | Overwrite with candidate |
  | `hermes-native/services/owned-ws/tests/input_progress.rs` | 9,849 | `24c733666fc8225330e93ccd85dea9b03e22b616d602183b1cf36666918f5147` | `null` | Missing | Add candidate |
  | `hermes-native/services/owned-ws/tests/test_vendor_integrity.py` | 2,996 | `b1b542e7b1d68f42d6419c703a0c8dec6b40200f37122235ddf386865e55f204` | `null` | Missing | Add candidate |
  | `hermes-native/services/owned-ws/vendor-patch-receipt.json` | 8,997 | `516389ab46529031ef70dc6db6a039d23d8bec280cc8a189b23ebdce17aa3235` | `e7bf19a9c586fc30355c6d104c94f7990c115d1236d9b58f8816515ae360a837` | Exists (`base_sha256` matches) | Overwrite with candidate |
  | `hermes-native/services/owned-ws/vendor-progress-patch.json` | 22,211 | `aedf801d1a660480e3a36f2529d8ded7ee0877a6ecbf6b701936d39d1bed434b` | `null` | Missing | Add candidate |
  | `hermes-native/services/owned-ws/vendor-progress.diff` | 10,844 | `c76d5f076b19b39b22a399ab015482a02f29fcab99633d30b91719355623c7f4` | `null` | Missing | Add candidate |
  | `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/frame/mod.rs` | 13,396 | `0ca5950198e0e12f4e696c87c311783bc61e3b7e8733c0f26fb23594de4c4d09` | `e036c36262bfb8e3dad2249ceb24ff9147c294592104542562a5259651cee898` | Exists (`base_sha256` matches) | Overwrite with candidate |
  | `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/mod.rs` | 37,637 | `0c8fee1820f482c59a7235c5e319774cc2a4b82061496a8b6c11b7ce8363d04b` | `61b6b0f1ec257d51921caaaa5f7c6d770f747091366b31135ff24010095b4c97` | Exists (`base_sha256` matches) | Overwrite with candidate |
  | `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/progress.rs` | 3,645 | `2793af71d5b0b21e5bac750516be9f7204f00bc0f1185f1b3960a8469d8d9009` | `null` | Missing | Add candidate (28th vendor file) |
  | `hermes-native/services/owned-ws/verify_vendor.py` | 8,706 | `bba3dde07e58f5a5f4c3771778ec884b264644bd3ed986dd2845ca19957db5e2` | `1c5fc7391ad18691e1738413fa61729ef3942ed8591604fd9f23e5032ac8b85c` | Exists (`base_sha256` matches) | Overwrite with candidate |

- **Preserved Staging Directories on Drive G:**:
  - `G:\Project_Ned\.soak_workspace\hermes-native-client-stage`: contains the 2 desktop-ui candidate files.
  - `G:\Project_Ned\.soak_workspace\hermes-ws-progress-stage`: contains the 9 owned-ws candidate files and full working Rust crate.
  - `G:\Project_Ned\.soak_workspace\hermes-socket-checkpoint-stage`: contains `Verify-Foundation.ps1`.

---

### 1.2 TypeScript Error TS2367 in `native-gateway-socket.ts`
- **Direct Compiler Reproduction**:
  Command executed:
  ```bash
  node G:\Personal_Assistant\hermes\hermes-agent\node_modules\typescript\bin\tsc \
    G:\Project_Ned\.soak_workspace\hermes-native-client-stage\hermes-native\apps\desktop-ui\src\native-gateway-socket.ts \
    --noEmit --strict --target ES2023 --lib ES2023,DOM
  ```
  Verbatim Compiler Error Output:
  ```
  G:/Project_Ned/.soak_workspace/hermes-native-client-stage/hermes-native/apps/desktop-ui/src/native-gateway-socket.ts(152,29): error TS2367: This comparison appears to be unintentional because the types '0' and '2' have no overlap.
  ```
- **Code Context in `native-gateway-socket.ts`**:
  - Line 74: `readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSING = 2; readonly CLOSED = 3`
  - Line 77: `#state: 0 | 1 | 2 | 3 = 0`
  - Line 100: `get readyState(): 0 | 1 | 2 | 3 { return this.#state }`
  - Lines 141–153 in `#start()`:
    ```typescript
    141: async #start() {
    142:   if (this.#terminal) return
    143:   if (this.#state !== this.CONNECTING) { this.#nativeRetired = true; this.#fail(); return }
    144:   try {
    145:     const opened = await this.#call(async () => {
    146:       const result = await this.#host.create(endpointPattern.exec(this.url)![1], this.#abort.signal)
    147:       if (!identity(result)) { this.#fence(); throw new Error('Invalid native identity') }
    148:       this.#identity = Object.freeze({ ...result })
    149:       if (this.#terminal || this.#state === this.CLOSING) void this.#retireHost(true)
    150:       return result
    151:     })
    152:     if (this.#terminal || this.#state === this.CLOSING) { void this.#retireHost(true); return }
    ```
- **Additional Peer Close Defect Observed in `native-gateway-socket.ts`**:
  - Line 202–206:
    ```typescript
    if (value.kind === 'close') {
      if (...) { this.#fail(); return }
      this.#nativeRetired = true
      this.#remoteClose = value as unknown as Extract<SocketEvent, { kind: 'close' }>
    ```
  - Line 205 prematurely sets `this.#nativeRetired = true` immediately upon receiving a peer close message, before `host.close()` has confirmed actor retirement via `#retireHost()` (line 258). This violates the core invariant: *"a peer close must not itself certify actor retirement."*

---

### 1.3 Vendored Tungstenite 0.30.0 Output Files & Newline Integrity
- **File Count**: 28 files in candidate (`hermes-progress-2` receipt) vs 27 files in base (`hermes-logsafe-1` receipt).
- **Added 28th File**: `src/protocol/progress.rs` (3,645 bytes, sha256 `2793af71d5b0b21e5bac750516be9f7204f00bc0f1185f1b3960a8469d8d9009`).
- **Newline Conventions and Verification Mechanics**:
  - Unmodified upstream files (22 files): Byte-identical to crates.io Tungstenite 0.30.0, LF newlines.
  - Log-safe sanitized files in revision 1 (5 files): Replaced 14 logging macros with `!("WebSocket protocol event.");`. Historically formatted with CRLF (`\r\n`).
  - Revision 2 (`hermes-progress-2`):
    - Two files modified for parser progress: `src/protocol/mod.rs` and `src/protocol/frame/mod.rs`.
    - These 2 files were explicitly converted from CRLF to LF (`value.replace("\r\n", "\n")` at line 198 of `verify_vendor.py`).
    - The remaining 3 log-patched files (`src/client.rs`, `src/handshake/client.rs`, `src/protocol/frame/frame.rs`) strictly retain CRLF (`\r\n`).
    - `src/protocol/progress.rs` is LF (`\n`).
- **Verifier Execution**:
  Direct execution of `python verify_vendor.py` against candidate vendor directory:
  ```
  INFO Vendor source receipt verified (28 files).
  Exit code: 0
  ```

---

### 1.4 Parser Progress Safety Invariants
- **Protocol Error Safety**:
  - In `src/protocol/progress.rs`: `FrameProgress` maintains a sticky `failed: bool` flag. Any call to `fail(&mut self)` sets `self.failed = true`. Subsequent calls to `check()`, `advance()`, `receive()`, `begin()`, `finish()`, or `snapshot()` return `Err(progress_error())` (`"WebSocket input progress exhausted"`).
  - In `src/protocol/mod.rs` (line 59) and `src/protocol/frame/mod.rs` (line 150): `self.progress.check()?;` guards parser entry. Once a protocol error occurs, subsequent observations never yield valid application state.
- **Peer Close Separation**:
  - In `hermes-native/services/owned-ws/tests/native_ws.rs`: Test `peer_initiated_close_is_observed_and_verified_separately_from_job_retirement` demonstrates that observing a peer close frame sets `close.peer_close_observed = true`, but the worker process remains active (`wait_timeout(Duration::ZERO)` is `None`). Actor retirement is only certified when `group.retire_captured(...)` completes.
- **Message Ordering Ahead of Terminal Frames**:
  - In `native-gateway-socket.ts`: When `value.kind === 'close'`, the close event is saved to `this.#remoteClose` (line 206), but `this.#finish(...)` is only called in `finally` of `#pumpReceive()` *after* all queued messages in `this.#incoming` have been dispatched and acknowledged (`!this.#incoming.length`).

---

### 1.5 Test Suite Locations and Independent Verification Results

All suites were located and independently executed against the candidate and foundation trees:

| Test Suite | File Location | Test Count | Direct Run Command | Observed Result |
|---|---|---|---|---|
| **owned-ws (Full)** | `services/owned-ws/tests/native_ws.rs`<br>`services/owned-ws/src/lib.rs`<br>`services/owned-ws/tests/input_progress.rs` | 19 tests | `cargo test --offline --locked --manifest-path .../owned-ws/Cargo.toml --all-features -- --test-threads=1` | **19 passed** (1 lib, 10 native_ws, 8 input_progress), 0 failed, in 2.04s |
| **owned-http** | `services/owned-http/tests/native_http.rs`<br>`services/owned-http/src/lib.rs`<br>`services/owned-http/src/ownership.rs` | 7 tests | `cargo test --offline --locked --manifest-path .../owned-http/Cargo.toml --all-features -- --test-threads=1` | **7 passed** (2 lib/ownership, 5 native_http), 0 failed, in 0.98s |
| **parser progress** | `services/owned-ws/tests/input_progress.rs` | 8 tests | Included in `owned-ws` cargo test run above | **8 passed**, 0 failed |
| **vendor tamper** | `services/owned-ws/tests/test_vendor_integrity.py` | 8 tests | `.\.venv\Scripts\python.exe -m pytest .../test_vendor_integrity.py -v` | **8 passed**, 0 failed, in 1.05s |

Breakdown of the 8 `test_vendor_integrity.py` tests:
1. `test_exact_vendor_inventory_passes`: PASSED
2. `test_modified_protocol_bytes_fail`: PASSED
3. `test_extra_unlisted_file_fails`: PASSED
4. `test_missing_file_fails`: PASSED
5. `test_wrong_revision_fails`: PASSED
6. `test_receipt_cannot_name_parent_path`: PASSED
7. `test_receipt_cannot_omit_changed_file_patch`: PASSED
8. `test_wrong_upstream_preimage_fails`: PASSED

---

### 1.6 Foundation Verification Script (`Verify-Foundation.ps1`)
- **Base Script**: `hermes-native/scripts/Verify-Foundation.ps1` (218 lines).
  - Runs 26 check groups.
  - Line 163–166 ran only `verify_vendor.py` as a single `owned-ws-vendor` check.
- **Candidate Script**: `G:\Project_Ned\.soak_workspace\hermes-socket-checkpoint-stage\Verify-Foundation.ps1` (225 lines).
  - Expands `owned-ws` verification to 4 distinct gates:
    ```powershell
    Invoke-Check -Name 'owned-ws-vendor' -Command $python -ToolArguments @($vendorVerifier)
    Invoke-Check -Name 'owned-ws-vendor-tests' -Command $python -ToolArguments @('-m', 'pytest', '-o', 'addopts=', $vendorTests, '--basetemp', $vendorTemp, '-q')
    Invoke-Check -Name 'owned-ws-vendor-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', $vendorVerifier, $vendorTests)
    Invoke-Check -Name 'owned-ws-vendor-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', $vendorVerifier, $vendorTests)
    ```
  - Runs `cargo test` for `owned-ws` with `--all-features`, automatically picking up the 8 `input_progress` tests alongside the 11 base tests (total 19 tests).
- **Upstream Pinned Commit Invariant**:
  `Verify-Foundation.ps1` enforces:
  ```powershell
  $resolvedUpstream = (Resolve-Path -LiteralPath $UpstreamRoot).Path
  $env:HERMES_UPSTREAM_ROOT = $resolvedUpstream
  ```
  `upstream.mjs` verifies that `UpstreamRoot` is checked out at exact commit `649d6c0391029f35959cfbc240eb3534a6667cf5`. (Currently, `G:\Personal_Assistant\hermes\hermes-agent` is on `1744a19e0df568c647e4f3ff9c37f2a284a282fb`, so any automated run must provide an `UpstreamRoot` pointing to a checkout or worktree at `649d6c0391029f35959cfbc240eb3534a6667cf5`).

---

## 2. Logic Chain

1. **Promotion Need**: The 12 candidate files in `socket-candidates-20261008.zip` contain the necessary implementations for Requirement R1 (Tungstenite progress patch, receipt, tests, candidate socket client). The 6 base files in the working directory match `base_sha256` from commit `2ffddc6`, while the 6 missing files exist only in the archive and `.soak_workspace`. Therefore, candidate promotion requires updating the 6 existing files and introducing the 6 missing files.
2. **TS2367 Root Cause**: In `native-gateway-socket.ts`, line 143 executes `if (this.#state !== this.CONNECTING) return;`. TypeScript's control flow analysis narrows the type of private field `#state` to literal type `0` (`CONNECTING`). Even though line 145 performs an asynchronous `await this.#call(...)` during which `#state` can transition to `CLOSING` (type `2`), TypeScript's property narrowing in async functions persists across `await` unless explicitly reset or read dynamically. At line 152, `this.#state === this.CLOSING` compares type `0` against type `2`, which have no overlap, directly triggering `error TS2367`.
3. **TS2367 Resolution**: Reading the state dynamically via the public getter `this.readyState === this.CLOSING` (or asserting `(this.#state as 0 | 1 | 2 | 3) === this.CLOSING` or `(this.#state as number) === this.CLOSING`) breaks the stale narrowing and resolves TS2367 cleanly with zero runtime behavioral changes.
4. **Peer Close Retirement Defect**: Setting `this.#nativeRetired = true` at line 205 upon receiving a peer `close` frame causes the client socket to declare retirement prematurely. In accordance with the project invariants and Rust tests (`peer_initiated_close_is_observed_and_verified_separately_from_job_retirement`), actor retirement must strictly be certified by the host via `#retireHost()` (line 258) upon receipt of `{ retired: true }`. Line 205 must therefore be removed or corrected.
5. **Vendor Integrity**: The 28 output files reconstructed under `hermes-progress-2` correctly account for all 22 unmodified LF files, the 3 CRLF log-patched files, the 2 LF-converted progress-patched files, and the 1 added LF file `progress.rs`. Verified by passing `verify_vendor.py` (28/28 files) and `test_vendor_integrity.py` (8/8 tests).
6. **Test Coverage Completeness**: The 19 owned-ws tests consist of 1 unit test in `src/lib.rs`, 10 integration tests in `tests/native_ws.rs`, and 8 parser progress tests in `tests/input_progress.rs`. The 7 owned-http tests consist of 2 unit tests in `src/lib.rs` and `src/ownership.rs`, plus 5 integration tests in `tests/native_http.rs`. All 19 WS tests, 7 HTTP tests, 8 progress tests, and 8 tamper tests execute and pass 100%.

---

## 3. Caveats

- **Read-Only Scope**: This report is purely investigatory. No files in `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned` were modified during this investigation.
- **Upstream Pinned Checkout Requirement**: `Verify-Foundation.ps1` requires that `$UpstreamRoot` be on commit `649d6c0391029f35959cfbc240eb3534a6667cf5`. `G:\Personal_Assistant\hermes\hermes-agent` is currently checked out at `1744a19e0d`. Running `Verify-Foundation.ps1` will require passing a checkout or worktree path checked out at `649d6c0391029f35959cfbc240eb3534a6667cf5`.
- **Desktop UI Backend Unavailability**: The production desktop shell (`apps/desktop-ui`) intentionally does not import `native-gateway-socket.ts` yet and must remain in the truthful backend-unavailable state until full live actor qualification is complete.

---

## 4. Conclusion

1. **Promotion Readiness**: The 12 candidate files in `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` are structurally sound, match their recorded sha256 checksums, and are ready for promotion into the worktree.
2. **TypeScript & Client Socket Fix**: In `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`:
   - Fix TS2367 at line 152 by replacing `this.#state === this.CLOSING` with `this.readyState === this.CLOSING` (and recheck line 159 with `this.readyState === this.CONNECTING`).
   - Fix line 205: Remove `this.#nativeRetired = true` so remote close does not self-certify retirement before host close receipt.
3. **Vendor Reconstruction**: All 28 files for Tungstenite 0.30.0 under `hermes-progress-2` reconstruct with exact byte and newline integrity (22 LF upstream, 3 CRLF log-patched, 2 LF progress-patched, 1 LF added).
4. **Test Suites**:
   - `owned-ws`: 19/19 tests pass cleanly.
   - `owned-http`: 7/7 tests pass cleanly.
   - `input_progress`: 8/8 tests pass cleanly.
   - `test_vendor_integrity.py`: 8/8 tests pass cleanly.
5. **Foundation Script**: Candidate `Verify-Foundation.ps1` successfully integrates the 4 new vendor gates (`owned-ws-vendor`, `owned-ws-vendor-tests`, `owned-ws-vendor-lint`, `owned-ws-vendor-format`) and runs all 19 `owned-ws` tests under `--all-features`.

---

## 5. Verification Method

To independently verify all claims made in this report, execute the following commands from the repository root:

1. **Verify Candidate Archive Hash**:
   ```powershell
   Get-FileHash docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip -Algorithm SHA256
   # Must equal: 4456AAD2639BE93F67AAA18840C3E8E4152B2AB6EB9FD7210CDC55544C168A3E
   ```

2. **Verify TS2367 Error Reproduction**:
   ```powershell
   node G:\Personal_Assistant\hermes\hermes-agent\node_modules\typescript\bin\tsc `
     G:\Project_Ned\.soak_workspace\hermes-native-client-stage\hermes-native\apps\desktop-ui\src\native-gateway-socket.ts `
     --noEmit --strict --target ES2023 --lib ES2023,DOM
   # Confirms TS2367 error at line 152 col 29.
   ```

3. **Verify 28 Vendor Output Files**:
   ```powershell
   python G:\Project_Ned\.soak_workspace\hermes-ws-progress-stage\hermes-native\services\owned-ws\verify_vendor.py
   # Output: INFO Vendor source receipt verified (28 files).
   ```

4. **Verify 8 Python Vendor Integrity Tamper Tests**:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest G:\Project_Ned\.soak_workspace\hermes-ws-progress-stage\hermes-native\services\owned-ws\tests\test_vendor_integrity.py -v
   # Output: 8 passed in ~1.05s
   ```

5. **Verify 19 Owned-WS Tests (including 8 Parser Progress Tests)**:
   ```powershell
   cargo test --offline --locked --manifest-path G:\Project_Ned\.soak_workspace\hermes-ws-progress-stage\hermes-native\services\owned-ws\Cargo.toml --all-features -- --test-threads=1
   # Output: 1 passed in src/lib.rs, 8 passed in tests/input_progress.rs, 10 passed in tests/native_ws.rs (Total 19 passed)
   ```

6. **Verify 7 Owned-HTTP Tests**:
   ```powershell
   cargo test --offline --locked --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1
   # Output: 2 passed in src/lib.rs & src/ownership.rs, 5 passed in tests/native_http.rs (Total 7 passed)
   ```

7. **Verify Foundation Script Gate Differences**:
   ```powershell
   Compare-Object (Get-Content hermes-native/scripts/Verify-Foundation.ps1) (Get-Content G:\Project_Ned\.soak_workspace\hermes-socket-checkpoint-stage\Verify-Foundation.ps1)
   # Inspect lines 163-171 showing the 4 added vendor check gates.
   ```
