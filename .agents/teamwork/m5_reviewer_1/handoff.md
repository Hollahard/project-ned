# Reviewer & Adversarial Critic Report — Milestone 5: Foundation, Transport & Desktop Shell Review

**Date**: 2026-10-09T17:27:00Z  
**Author**: Reviewer 1 (`m5_reviewer_1`)  
**Roles**: `reviewer`, `critic`  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m5_reviewer_1`  
**Target Milestone**: Milestone 5 (Foundation, Transport & Desktop Shell Review)  
**Verdict**: **APPROVE**  

---

## Review Summary

**Verdict**: **APPROVE**  
**Integrity Status**: **CLEAN (Zero Integrity Violations Detected)**  
**Adversarial Risk Assessment**: **LOW**  

Reviewer 1 has independently executed, audited, and stress-tested all components of the Foundation, Transport, and Desktop Shell subsystems. All 7 review tasks defined in the dispatch completed with 100% pass rates. Zero integrity violations, dummy facades, hardcoded test stubs, or unauthorized shortcuts were found.

---

## 1. Observation

### 1.1 Foundation Verification (`Verify-Foundation.ps1`, 54 Check Groups)
- **Execution Command**:
  ```powershell
  cmd.exe /c "pwsh -NoProfile -Command "". .\.venv\Scripts\Activate.ps1; & hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -NativeFixtures"" > verify_foundation.log 2>&1"
  ```
- **Execution Result**: Exit code `0`. All 54 check groups passed:
  1. `renderer-tests` (0.436s)
  2. `upstream-baseline` (1.66s)
  3. `renderer-typecheck` (13.679s)
  4. `gateway-contracts` (0.221s)
  5. `inference-tests` (1.054s)
  6. `inference-lint` (0.091s)
  7. `inference-format` (0.121s)
  8. `model-catalog-tests` (1.114s)
  9. `model-catalog-lint` (0.088s)
  10. `model-catalog-format` (0.098s)
  11. `catalog-host-python-lint` (0.089s)
  12. `catalog-host-python-format` (0.09s)
  13. `catalog-host-python-tests` (0.929s)
  14. `managed-pack-tests` (1.354s)
  15. `managed-pack-lint` (0.089s)
  16. `managed-pack-format` (0.155s)
  17. `managed-pack-config` (0.243s)
  18. `control-worker-lint` (0.09s)
  19. `control-worker-format` (0.088s)
  20. `control-worker-tests` (1.713s)
  21. `renderer-integration` (5.896s)
  22. `backend-host-lint` (0.089s)
  23. `backend-host-format` (0.089s)
  24. `backend-host-tests` (2.478s)
  25. `owned-ws-vendor` (0.103s) — **Vendor Gate 1**
  26. `owned-ws-vendor-tests` (1.468s) — **Vendor Gate 2**
  27. `owned-ws-vendor-lint` (0.088s) — **Vendor Gate 3**
  28. `owned-ws-vendor-format` (0.085s) — **Vendor Gate 4**
  29. `resource-host-format` (0.124s)
  30. `resource-host-lint` (0.29s)
  31. `resource-host-tests` (1.406s)
  32. `preview-watch-format` (0.105s)
  33. `preview-watch-lint` (0.493s)
  34. `preview-watch-tests` (4.335s)
  35. `control-host-format` (0.12s)
  36. `control-host-lint` (0.491s)
  37. `control-host-tests` (2.049s)
  38. `catalog-host-format` (0.144s)
  39. `catalog-host-lint` (0.499s)
  40. `catalog-host-tests` (2.663s)
  41. `owned-http-format` (0.112s)
  42. `owned-http-lint` (0.166s)
  43. `owned-http-tests` (1.211s)
  44. `owned-ws-format` (0.115s)
  45. `owned-ws-lint` (0.201s)
  46. `owned-ws-tests` (2.277s)
  47. `terminal-host-format` (0.113s)
  48. `terminal-host-lint` (0.176s)
  49. `terminal-host-tests` (0.653s)
  50. `webview2-guest-format` (0.108s)
  51. `webview2-guest-lint` (0.895s)
  52. `webview2-guest-tests` (0.411s)
  53. `webview-native-build` (0.203s)
  54. `webview-native-run` (1.337s)
- **Evidence Output**:
  - `hermes-native/.checks/verification.latest.json` written with `"completed": true`, `"passed": true`, `"native_fixtures_requested": true`.

### 1.2 Owned WebSocket Test Suite (`hermes-native/services/owned-ws/`, 19 Tests)
- **Execution Command**:
  ```powershell
  cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features > test_owned_ws.txt 2>&1"
  ```
- **Execution Result**: Exit code `0`. **19 passed; 0 failed**:
  - `src/lib.rs` (1 passed):
    * `tests::credentials_and_hard_bounds_are_finite ... ok`
  - `tests/input_progress.rs` (8 passed):
    * `all_segment_boundaries_preserve_unicode_and_control_interleaving ... ok`
    * `coalesced_complete_message_and_partial_extended_header_keep_distinct_ranges ... ok`
    * `fragmented_message_survives_ping_pong_and_coalesced_next_partial ... ok`
    * `idle_partial_header_payload_and_completion_have_exact_wire_offsets ... ok`
    * `offsets_include_mask_header_and_malformed_inputs_still_fail ... ok`
    * `partial_eof_remains_protocol_error_not_completed_frame ... ok`
    * `preloaded_handshake_tail_starts_at_websocket_zero_and_read_is_observational ... ok`
    * `progress_arithmetic_overflow_and_invalid_advance_are_sticky ... ok`
  - `tests/native_ws.rs` (10 passed):
    * `auth_failure_redirect_extensions_subprotocol_and_duplicate_upgrade_fail ... ok`
    * `blocked_write_and_read_retirement_are_bounded_without_retry ... ok`
    * `close_timeout_control_flood_and_retirement_never_claim_success ... ok`
    * `coalesced_first_frame_and_fragment_boundaries_are_preserved ... ok`
    * `local_oversized_send_is_rejected_without_changing_healthy_socket ... ok`
    * `malformed_oversized_and_slow_peers_fail_closed_within_total_deadline ... ok`
    * `peer_initiated_close_is_observed_and_verified_separately_from_job_retirement ... ok`
    * `root_and_descendant_echo_text_binary_and_clean_close ... ok`
    * `trace_logger_and_owned_files_never_contain_credential_or_payload_canaries ... ok`
    * `unrelated_listener_receives_zero_bytes_and_survives ... ok`

### 1.3 Owned HTTP Test Suite (`hermes-native/services/owned-http/`, 7 Tests)
- **Execution Command**:
  ```powershell
  cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features > test_owned_http.txt 2>&1"
  ```
- **Execution Result**: Exit code `0`. **7 passed; 0 failed**:
  - `src/lib.rs` / `src/ownership.rs` (2 passed):
    * `ownership::tests::exact_reversed_tuple_established_only_and_unique ... ok`
    * `tests::request_contract_is_finite_and_header_injection_is_rejected ... ok`
  - `tests/native_http.rs` (5 passed):
    * `allowed_post_duplicate_auth_and_local_validation_preserve_contract ... ok`
    * `malformed_oversized_ambiguous_redirect_truncated_and_extra_responses_fail_closed ... ok`
    * `owned_root_and_descendant_all_supported_framings ... ok`
    * `slow_trickle_cannot_extend_absolute_deadline ... ok`
    * `unrelated_established_listener_receives_no_http_bytes_and_survives ... ok`

### 1.4 Python Vendor Tamper Test Suite (`test_vendor_integrity.py`, 8 Tests)
- **Execution Command**:
  ```powershell
  cmd.exe /c ".\.venv\Scripts\pytest.exe hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > test_pytest_vendor.txt 2>&1"
  ```
- **Execution Result**: Exit code `0`. **8 passed in 1.08s**:
  - `test_exact_vendor_inventory_passes`: PASSED
  - `test_modified_protocol_bytes_fail`: PASSED
  - `test_extra_unlisted_file_fails`: PASSED
  - `test_missing_file_fails`: PASSED
  - `test_wrong_revision_fails`: PASSED
  - `test_receipt_cannot_name_parent_path`: PASSED
  - `test_receipt_cannot_omit_changed_file_patch`: PASSED
  - `test_wrong_upstream_preimage_fails`: PASSED

### 1.5 TypeScript Typecheck (`typecheck.mjs`, 0 Errors)
- **Execution Command**:
  ```cmd
  cmd.exe /c "set HERMES_UPSTREAM_ROOT=G:\Personal_Assistant\hermes\hermes-agent&& node hermes-native/apps/desktop-ui/scripts/typecheck.mjs > test_typecheck.txt 2>&1"
  ```
- **Execution Result**: Exit code `0`. **0 errors, 0 warnings**.
- Verified fix in `hermes-native/apps/desktop-ui/src/native-gateway-socket.ts`:
  - Lines 149, 152, 159 evaluate dynamic readiness via `this.readyState === this.CLOSING` and `this.readyState === this.CONNECTING`, eliminating TS2367 type narrowing conflict with private `#state`.

### 1.6 Desktop UI Truthful Backend-Unavailable Reporting
- **Code Inspection**:
  - `hermes-native/apps/desktop-ui/src/host-adapter.ts`:
    * Line 46: `readonly binding: 'native-injected' | 'unavailable'`
    * Line 72: `if (disposed || !transport) return Promise.reject(new CapabilityUnavailableError(method))`
    * Line 88: `if (disposed || !transport) throw new CapabilityUnavailableError('events.${name}')`
    * Line 147: `binding: transport ? 'native-injected' : 'unavailable'`
- **Test Execution**:
  - Command: `cmd.exe /c "node --test hermes-native/apps/desktop-ui/tests/host-adapter.test.mjs > test_host_adapter.txt 2>&1"`
  - Result: Exit code `0`. **15 passed, 0 failed** in 81.46ms.
  - Verifies that when native transport is absent, the adapter rejects calls with `CapabilityUnavailableError` and refuses to manufacture synthetic connection, model, or version success.

### 1.7 Baseline Dirty File Hash Verification (100% Byte-Identical)
- **Execution Command**:
  ```powershell
  cmd.exe /c ".\.venv\Scripts\python.exe .agents/teamwork/m5_reviewer_1/check_hashes.py > test_dirty_hashes.txt 2>&1"
  ```
- **Computed SHA-256 Hashes vs `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`**:
  1. `G:\Project_Ned\apps\desktop\src-tauri\src\lib.rs`:
     - Expected: `5F779262B46E2AF882E28D3C43547840CCA16CAF7E64EB2CB907DFC2F46507A9`
     - Actual:   `5F779262B46E2AF882E28D3C43547840CCA16CAF7E64EB2CB907DFC2F46507A9` (MATCH: True)
  2. `G:\Project_Ned\apps\desktop\src-tauri\src\proxy.rs`:
     - Expected: `4BA5FDDA63C12F7275F81506D01B535A154259D2C0F0A2A132C377BEE505EDE3`
     - Actual:   `4BA5FDDA63C12F7275F81506D01B535A154259D2C0F0A2A132C377BEE505EDE3` (MATCH: True)
  3. `G:\Project_Ned\apps\desktop\src-tauri\tauri.conf.json`:
     - Expected: `1843E0D02AB9D344AACAB0B9292FE1E2AD1D98D700D77659612F52391D7EEED0`
     - Actual:   `1843E0D02AB9D344AACAB0B9292FE1E2AD1D98D700D77659612F52391D7EEED0` (MATCH: True)
  4. `G:\Project_Ned\apps\desktop\vite.config.ts`:
     - Expected: `D4F0ED4FE30358370157528C73510C8C1BF7644A8775345CEC22D90DBEB8B0AF`
     - Actual:   `D4F0ED4FE30358370157528C73510C8C1BF7644A8775345CEC22D90DBEB8B0AF` (MATCH: True)
- **Result**: **100% byte-identical across all 4 files**.

### 1.8 Orphaned Process Hygiene
- Checked process table for lingering background processes:
  - `pytest.exe`: 0 processes running.
  - `ping.exe`: 0 processes running.

---

## 2. Logic Chain

1. **Vendor Verification Gate Logic**: The 4 vendor gates in `Verify-Foundation.ps1` (`owned-ws-vendor`, `owned-ws-vendor-tests`, `owned-ws-vendor-lint`, `owned-ws-vendor-format`) invoke `verify_vendor.py`, `test_vendor_integrity.py`, `ruff check`, and `ruff format --check`. Because `Invoke-Check` throws if `$LASTEXITCODE -ne 0`, any alteration or missing file in the 28-file vendored Tungstenite directory immediately halts the foundation runner. All 4 gates passed.
2. **Wire Offset & Monotonicity Verification**: `tests/input_progress.rs` exercises `FrameProgress` and `InputProgress` under complex interleaving (coalesced headers, fragmented messages, ping-pong interleaving, and partial EOF). Passing all 8 tests proves that wire offset tracking is monotonic and accurate.
3. **Sticky Error Latching Integrity**: In `FrameProgress` (`vendor/tungstenite/src/protocol/progress.rs`), fatal protocol errors or integer arithmetic overflows call `fail()`, latching `failed = true`. Once latched, all public methods return `Err("WebSocket input progress exhausted")`, preventing post-error observations from ever synthesizing valid application state.
4. **Peer-Close Host Retirement Invariant**: In `native-gateway-socket.ts`, observing a peer close does not set `this.#nativeRetired = true`. Instead, the socket drains and dispatches all preceding queued incoming messages, fires `CloseEvent`, and requests `this.#host.close()`. Only when the host responds with `receipt.retired === true` is `#nativeRetired` set to `true`.
5. **UI Truthful Reporting**: The desktop UI host adapter strictly enforces `binding: 'unavailable'` when no native transport is injected, throwing `CapabilityUnavailableError` rather than synthesizing false backend connection success.
6. **Workspace Invariant Compliance**: All 4 baseline dirty files maintain 100% bit-identical SHA-256 hashes compared to `preexisting-dirty-file-hashes.json`.

---

## 3. Adversarial Critic Challenge Analysis

### 3.1 Integrity Violation Assessment
- **Hardcoded test results**: None detected. Tests connect to live loopback fixtures, read dynamic TCP streams, and calculate real SHA-256 digests.
- **Dummy/facade implementations**: None detected. Full logic implemented in Rust, TypeScript, and Python.
- **Shortcuts / Bypasses**: None detected. All checks run through complete automated verifiers.
- **Fabricated verification logs**: None detected. All commands were run independently during this turn and logs inspected.
- **Self-certifying work**: None detected. Host retirement strictly requires bidirectional confirmation.

### 3.2 Assumption & Stress Testing
1. **Challenge 1: Shell Execution Invariant on `Verify-Foundation.ps1`**
   - *Attack Scenario*: Attempting to run `powershell -ExecutionPolicy Bypass -File hermes-native/scripts/Verify-Foundation.ps1 -NativeFixtures` in standard Windows PowerShell 5.1.
   - *Observation*: Execution fails with `ScriptRequiresUnmatchedPSVersion` because line 1 mandates `#Requires -Version 7.0`.
   - *Mitigation*: The runner must be invoked via PowerShell Core (`pwsh.exe`), passing the mandatory parameters `-UpstreamRoot` and `-TabbySource`.
2. **Challenge 2: Environment Variable Parsing in cmd.exe for `typecheck.mjs`**
   - *Attack Scenario*: Setting `HERMES_UPSTREAM_ROOT` in cmd.exe with trailing space before `&&` (`set VAR=path && cmd`).
   - *Observation*: cmd.exe retains the space in the variable value, causing `lstat 'path '` to fail with `ENOENT`.
   - *Mitigation*: Set without trailing whitespace (`set VAR=path&& cmd`) or run through PowerShell.
3. **Challenge 3: Offline Feature Gating in `owned-ws`**
   - *Attack Scenario*: Running `cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml` without `--all-features`.
   - *Observation*: Only 9 tests execute (1 unit, 8 progress); the 10 integration tests in `tests/native_ws.rs` are skipped because the fixture binary requires `test-fixture`.
   - *Mitigation*: `Verify-Foundation.ps1` explicitly passes `--all-features`, ensuring all 19 tests are executed.

---

## 4. Caveats

- **PowerShell 7+ Requirement**: As noted in Challenge 1, `Verify-Foundation.ps1` strictly requires PowerShell Core 7 (`pwsh.exe`) and mandatory arguments `-UpstreamRoot` and `-TabbySource`.
- **Pinned Upstream Worktree**: `Verify-Foundation.ps1` verifies the pinned commit `649d6c0391029f35959cfbc240eb3534a6667cf5` in `G:\Personal_Assistant\hermes\hermes-agent`.
- **No other caveats**: All 7 review tasks independently executed and confirmed 100% passing.

---

## 5. Conclusion & Verdict

**Verdict**: **APPROVE**

Milestone 5 deliverables for Foundation, Transport, and Desktop Shell Review satisfy all requirements:
1. `Verify-Foundation.ps1 -NativeFixtures` completes with 54/54 check groups passing (including all 4 vendor gates).
2. `owned-ws` cargo tests pass 19/19 with `--all-features`.
3. `owned-http` cargo tests pass 7/7.
4. Python vendor integrity suite passes 8/8 tamper tests.
5. TypeScript typecheck passes with 0 errors on `native-gateway-socket.ts`.
6. Desktop UI truthfully reports backend unavailable.
7. Baseline dirty file hashes match 100% against `preexisting-dirty-file-hashes.json`.
8. Zero orphaned processes detected; zero integrity violations detected.

---

## 6. Verification Method

To independently reproduce this verification:

```powershell
# 1. Foundation Verification (54 checks via pwsh)
cmd.exe /c "pwsh -NoProfile -Command "". .\.venv\Scripts\Activate.ps1; & hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -NativeFixtures"" > verify_foundation.log 2>&1"

# 2. Owned WebSocket cargo test (19 tests)
cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features > test_owned_ws.txt 2>&1"

# 3. Owned HTTP cargo test (7 tests)
cmd.exe /c "cargo test --offline --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features > test_owned_http.txt 2>&1"

# 4. Python vendor tamper tests (8 tests)
cmd.exe /c ".\.venv\Scripts\pytest.exe hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > test_pytest_vendor.txt 2>&1"

# 5. TypeScript typecheck (0 errors)
cmd.exe /c "set HERMES_UPSTREAM_ROOT=G:\Personal_Assistant\hermes\hermes-agent&& node hermes-native/apps/desktop-ui/scripts/typecheck.mjs > test_typecheck.txt 2>&1"

# 6. Desktop UI truthful reporting (15 tests)
cmd.exe /c "node --test hermes-native/apps/desktop-ui/tests/host-adapter.test.mjs > test_host_adapter.txt 2>&1"

# 7. Baseline dirty file hash check (4/4 files match)
cmd.exe /c ".\.venv\Scripts\python.exe .agents/teamwork/m5_reviewer_1/check_hashes.py > test_dirty_hashes.txt 2>&1"
```
