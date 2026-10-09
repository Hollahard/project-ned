# Handoff Report — Milestone 1: Candidate Socket Promotion & Client Typecheck Resolution

**Date**: 2026-10-09T14:25:00Z  
**Author**: Worker M1 (`worker_m1_1`)  
**Parent Orchestrator**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m1_1`  
**Checkpoint Commit**: `2afa8eafe5528fe3b352c266ec0e1e76395c46a9` on branch `codex/hermes-native-foundation`  

---

## 1. Observation

### 1.1 Candidate Archive & Manifest Inspection
- Manifest: `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.json`
- Candidate archive: `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.zip` (SHA-256: `4456aad2639be93f67aaa18840c3e8e4152b2ab6eb9fd7210cdc55544c168a3e`, 43,032 bytes).
- Candidate files matching manifest and verified against pre-staged copies in `G:\Project_Ned\.soak_workspace\hermes-native-client-stage` and `hermes-ws-progress-stage`.
- Out of 12 candidate files, 11 belong to exclusive write ownership of Worker M1:
  1. `hermes-native/apps/desktop-ui/scripts/typecheck.mjs` (2,433 B; sha256 `d68011aec53992db0163f2473d571e762ef5ca6fdf85407f2cbbc368e8fc2d41`)
  2. `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts` (promoted and patched)
  3. `hermes-native/services/owned-ws/tests/input_progress.rs` (9,849 B; sha256 `24c733666fc8225330e93ccd85dea9b03e22b616d602183b1cf36666918f5147`)
  4. `hermes-native/services/owned-ws/tests/test_vendor_integrity.py` (2,996 B; sha256 `b1b542e7b1d68f42d6419c703a0c8dec6b40200f37122235ddf386865e55f204`)
  5. `hermes-native/services/owned-ws/vendor-patch-receipt.json` (8,997 B; sha256 `516389ab46529031ef70dc6db6a039d23d8bec280cc8a189b23ebdce17aa3235`)
  6. `hermes-native/services/owned-ws/vendor-progress-patch.json` (22,211 B; sha256 `aedf801d1a660480e3a36f2529d8ded7ee0877a6ecbf6b701936d39d1bed434b`)
  7. `hermes-native/services/owned-ws/vendor-progress.diff` (10,844 B; sha256 `c76d5f076b19b39b22a399ab015482a02f29fcab99633d30b91719355623c7f4`)
  8. `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/frame/mod.rs` (13,396 B; sha256 `0ca5950198e0e12f4e696c87c311783bc61e3b7e8733c0f26fb23594de4c4d09`)
  9. `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/mod.rs` (37,637 B; sha256 `0c8fee1820f482c59a7235c5e319774cc2a4b82061496a8b6c11b7ce8363d04b`)
  10. `hermes-native/services/owned-ws/vendor/tungstenite/src/protocol/progress.rs` (3,645 B; sha256 `2793af71d5b0b21e5bac750516be9f7204f00bc0f1185f1b3960a8469d8d9009`)
  11. `hermes-native/services/owned-ws/verify_vendor.py` (8,706 B; sha256 `bba3dde07e58f5a5f4c3771778ec884b264644bd3ed986dd2845ca19957db5e2`)
  *(The 12th file `hermes-native/scripts/Verify-Foundation.ps1` belongs exclusively to Milestone 2 and was not touched).*

### 1.2 TypeScript TS2367 Reproduction & Resolution
- **Initial error verbatim**:
  ```
  error TS2367: This comparison appears to be unintentional because the types '0' and '2' have no overlap.
  ```
  Occurred at line 152 in candidate `native-gateway-socket.ts` where private property `#state` was statically narrowed to literal `0` (`CONNECTING`) by line 143 `if (this.#state !== this.CONNECTING) return`, and subsequent check `if (this.#terminal || this.#state === this.CLOSING)` compared type `0` to literal `2`.
- **Resolution**:
  Replaced narrowed private field comparisons with the dynamic getter `this.readyState`:
  - Line 149: `if (this.#terminal || this.readyState === this.CLOSING) void this.#retireHost(true)`
  - Line 152: `if (this.#terminal || this.readyState === this.CLOSING) { void this.#retireHost(true); return }`
  - Line 159: `if (!this.#terminal && this.readyState === this.CONNECTING) {`
- **Resulting tsc output**:
  Command: `node G:\Personal_Assistant\hermes\hermes-agent\node_modules\typescript\bin\tsc hermes-native/apps/desktop-ui/src/native-gateway-socket.ts --noEmit --strict --target ES2023 --lib ES2023,DOM`
  Exit code: `0`, zero errors, zero warnings.

### 1.3 Peer-Close Retirement Invariant Resolution
- In candidate `native-gateway-socket.ts` lines 202–210:
  Line 205 originally had `this.#nativeRetired = true` immediately upon receiving `value.kind === 'close'`.
- This violated the invariant: *"a peer close must not itself certify actor retirement."*
- **Resolution**:
  - Removed `this.#nativeRetired = true` from line 205.
  - In `finally` block of `#pumpReceive` (lines 234–239), ensured all preceding incoming frames in `#incoming` are drained and dispatched in wire order before `this.#finish` fires `SocketCloseEvent`.
  - Added `void this.#retireHost(false)` following `#finish`, ensuring `this.#host.close()` is called and host retirement is certified only when receipt arrives with `receipt.retired === true` at line 258:
    ```typescript
    if (!record(receipt) || !exact(receipt, ['socketId', 'generation', 'retired']) || !same(receipt, owner) || receipt.retired !== true) throw new Error('Invalid retirement receipt')
    this.#nativeRetired = true
    ```

### 1.4 Vendored Tungstenite 0.30.0 (28 Files) Verification
- Reconstructed 28 vendor files under `hermes-progress-2` receipt:
  - 22 unmodified upstream files (LF)
  - 3 log-patched files (`src/client.rs`, `src/handshake/client.rs`, `src/protocol/frame/frame.rs`) with CRLF
  - 2 progress-patched files (`src/protocol/mod.rs`, `src/protocol/frame/mod.rs`) LF-normalized
  - 1 added 28th file (`src/protocol/progress.rs`) LF-normalized
- Execution of `python hermes-native/services/owned-ws/verify_vendor.py`:
  ```
  INFO Vendor source receipt verified (28 files).
  ```
  Exit code: `0`.

### 1.5 Test Suite Results
1. **Python Vendor Integrity Tamper Suite** (`hermes-native/services/owned-ws/tests/test_vendor_integrity.py`):
   - Command: `.\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v`
   - Result: **8 passed in 0.93s** (100% passing)
     - `test_exact_vendor_inventory_passes`: PASSED
     - `test_modified_protocol_bytes_fail`: PASSED
     - `test_extra_unlisted_file_fails`: PASSED
     - `test_missing_file_fails`: PASSED
     - `test_wrong_revision_fails`: PASSED
     - `test_receipt_cannot_name_parent_path`: PASSED
     - `test_receipt_cannot_omit_changed_file_patch`: PASSED
     - `test_wrong_upstream_preimage_fails`: PASSED
2. **Owned WebSocket Test Suite** (`hermes-native/services/owned-ws/`):
   - Command: `cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1`
   - Result: **19 passed, 0 failed** (1 lib, 8 input_progress, 10 native_ws)
     - `src/lib.rs`: 1 passed
     - `tests/input_progress.rs`: 8 passed (all wire offsets, monotonic tracking, and sticky error latching verified)
     - `tests/native_ws.rs`: 10 passed (including peer-initiated close separation test)
3. **Owned HTTP Test Suite** (`hermes-native/services/owned-http/`):
   - Command: `cargo test --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1`
   - Result: **7 passed, 0 failed** (2 lib/ownership, 5 native_http)
4. **Code Quality & Linting**:
   - `ruff check`: All checks passed.
   - `ruff format --check`: 2 files already formatted.

---

## 2. Logic Chain

1. **Promotion Soundness**: Candidate files in `socket-candidates-20261008.zip` and stage directories were verified against SHA-256 preimages in `socket-candidates-20261008.json` prior to promotion. The 25 vendor files already present in the repository from base commit `2ffddc6` matched upstream preimages byte-for-byte; promoting the 3 modified/added files (`frame/mod.rs`, `mod.rs`, `progress.rs`) completed the 28-file set without introducing untracked or corrupt bytes.
2. **Typecheck Resolution**: TypeScript's control flow analysis narrows private fields (`#state`) within a function scope. Following `#state !== this.CONNECTING`, `#state` was narrowed to `0`. After asynchronous `await this.#call(...)`, the narrowing was not refreshed, causing `this.#state === this.CLOSING` to compare `0 === 2` and fail statically with TS2367. Accessing `this.readyState` resolves the value dynamically via the public getter, preventing static narrowing collapse across asynchronous turns while preserving type safety (`0 | 1 | 2 | 3`).
3. **Peer-Close Invariant**: Setting `#nativeRetired = true` inside the event bus receiver when `value.kind === 'close'` caused the socket to self-certify actor retirement upon observing remote close. Removing this line ensures `#nativeRetired` remains `false`. Calling `#retireHost(false)` after preceding messages are drained triggers `this.#host.close(owner, ...)`; only upon receiving `{ retired: true }` from the host is `#nativeRetired` set to `true`, strictly preserving the actor retirement boundary.
4. **Parser Progress Safety**: In `InputProgress` (`vendor/tungstenite/src/protocol/progress.rs`), fatal protocol errors invoke `fail()`, which latches the sticky `failed: bool` flag. The 8 tests in `input_progress.rs` verify that once latched, any subsequent calls to `check()`, `advance()`, `receive()`, `begin()`, `finish()`, or `snapshot()` return `Err("WebSocket input progress exhausted")`, preventing post-error observations from ever synthesizing valid application state.

---

## 3. Caveats

- **Scope Adherence**: `Verify-Foundation.ps1` was not modified in Milestone 1 because it is exclusively assigned to Milestone 2.
- **Production Desktop Shell Wiring**: In accordance with the Truthful Backend-Unavailable reporting contract (Feature 12), `apps/desktop-ui` continues reporting backend unavailable until full gateway qualification in Milestone 2.
- **No other caveats**: All tasks in Milestone 1 scope completed with zero worktree dirt outside the designated files.

---

## 4. Conclusion

Milestone 1 is fully complete and verified:
- Candidate files promoted and hash-verified against manifest preimages.
- Strict TypeScript compilation of `native-gateway-socket.ts` passes with 0 errors.
- Peer-close actor retirement defect resolved with strict host receipt certification.
- All 28 Tungstenite 0.30.0 vendor files reconstructed and verified under `hermes-progress-2` receipt with LF/CRLF integrity.
- All 19 owned-ws tests (including 8 parser progress tests), 8 Python vendor tamper tests, and 7 owned-http tests pass 100%.

Milestone 2 (Owned WebSocket & Transport Foundation Verification) is ready to proceed.

---

## 5. Verification Method

To independently reproduce and verify Milestone 1 results, run the following commands from the repository root `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`:

```powershell
# 1. Verify TypeScript strict typecheck (must produce 0 errors and exit 0)
cmd.exe /c "node G:\Personal_Assistant\hermes\hermes-agent\node_modules\typescript\bin\tsc hermes-native/apps/desktop-ui/src/native-gateway-socket.ts --noEmit --strict --target ES2023 --lib ES2023,DOM > tsc_run.txt 2>&1"
# Inspect tsc_run.txt, verify exit code 0, then delete.

# 2. Verify 28 Tungstenite vendor files and LF/CRLF receipt integrity (must exit 0 with "INFO Vendor source receipt verified (28 files).")
cmd.exe /c ".\.venv\Scripts\python.exe hermes-native/services/owned-ws/verify_vendor.py > vendor_run.txt 2>&1"
# Inspect vendor_run.txt, verify exit code 0, then delete.

# 3. Verify Python vendor tamper test suite (must pass 8/8 tests)
cmd.exe /c ".\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > pytest_vendor.txt 2>&1"
# Inspect pytest_vendor.txt, verify 8 passed, then delete.

# 4. Verify owned-ws Rust crate tests (must pass 19/19 tests: 1 lib, 8 input_progress, 10 native_ws)
cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1 > cargo_ws.txt 2>&1"
# Inspect cargo_ws.txt, verify 19 passed, then delete.
```
