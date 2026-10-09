# Review & Adversarial Critic Report — Milestone 2: Owned WebSocket & Transport Foundation Verification

**Date**: 2026-10-09T15:05:00Z  
**Author**: Reviewer 1 (`m2_reviewer_1`)  
**Roles**: `reviewer`, `critic`  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m2_reviewer_1`  
**Target Milestone**: Milestone 2 (Owned WebSocket & Transport Foundation Verification)  
**Verdict**: **APPROVE**  

---

## Review Summary

**Verdict**: **APPROVE**  
**Integrity Status**: **CLEAN (Zero Integrity Violations Detected)**  
**Adversarial Risk Assessment**: **LOW**  

Milestone 2 deliverables have been independently executed, inspected, and stress-tested. All 19 owned-ws tests, 7 owned-http tests, 8 Python vendor tamper tests, and 54 foundation check groups in `Verify-Foundation.ps1` execute cleanly with 100% pass rates. The promoted candidate `Verify-Foundation.ps1` matches its candidate preimage bit-for-bit, correctly incorporates the 4 new vendor gates, adds `--all-features` to cargo test and clippy, and strictly enforces truthfulness in desktop UI capability reporting.

---

## 1. Observation

### 1.1 Candidate Promotion & SHA-256 Hash Preimage Verification
- Target file: `hermes-native/scripts/Verify-Foundation.ps1`
  - Size: 15,293 bytes.
  - Computed SHA-256: `50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230`.
- Candidate Preimage in `docs/hermes-native-desktop/implementation-evidence/socket-candidates-20261008.json`:
  ```json
  {
    "path": "hermes-native/scripts/Verify-Foundation.ps1",
    "bytes": 15293,
    "sha256": "50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230",
    "base_sha256": "09c256f036c75253f71167d5f8219e71c6b2fc368b3e072949a8a2cb6550aef0",
    "local_source": "G:\\Project_Ned\\.soak_workspace\\hermes-socket-checkpoint-stage\\Verify-Foundation.ps1"
  }
  ```
  Verified: The worktree file is bit-identical to the candidate preimage.

- Verbatim Diff against base:
  ```diff
  --- a/hermes-native/scripts/Verify-Foundation.ps1
  +++ b/hermes-native/scripts/Verify-Foundation.ps1
  @@ -160,7 +160,14 @@ try {
           Invoke-Check -Name 'backend-host-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $backend 'pyproject.toml'), (Join-Path $backend 'tests'), '--basetemp', $backendTemp, '-q')
       }
   
  -    Invoke-Check -Name 'owned-ws-vendor' -Command $python -ToolArguments @((Join-Path $nativeRoot 'services/owned-ws/verify_vendor.py'))
  +    $ownedWs = Join-Path $nativeRoot 'services/owned-ws'
  +    $vendorVerifier = Join-Path $ownedWs 'verify_vendor.py'
  +    $vendorTests = Join-Path $ownedWs 'tests/test_vendor_integrity.py'
  +    Invoke-Check -Name 'owned-ws-vendor' -Command $python -ToolArguments @($vendorVerifier)
  +    $vendorTemp = New-TestDirectory -Label 'owned-ws-vendor-pytest'
  +    Invoke-Check -Name 'owned-ws-vendor-tests' -Command $python -ToolArguments @('-m', 'pytest', '-o', 'addopts=', $vendorTests, '--basetemp', $vendorTemp, '-q')
  +    Invoke-Check -Name 'owned-ws-vendor-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', $vendorVerifier, $vendorTests)
  +    Invoke-Check -Name 'owned-ws-vendor-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', $vendorVerifier, $vendorTests)
   
       foreach ($package in @('services/resource-host', 'services/preview-watch', 'services/control-host', 'services/catalog-host', 'services/owned-http', 'services/owned-ws', 'services/terminal-host', 'spikes/webview2-guest')) {
           $manifest = Join-Path (Join-Path $nativeRoot $package) 'Cargo.toml'
  ```
  Line 183: `if ($label -eq 'owned-ws') { $lintArgs += '--all-features' }`  
  Line 188: `if ($label -eq 'owned-ws') { $testArgs += '--all-features' }`

### 1.2 Independent Test Execution Results

1. **`owned-ws` Cargo Test Suite (19 tests)**:
   - Command: `cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1"`
   - Output:
     - `src/lib.rs`: 1 passed (`tests::credentials_and_hard_bounds_are_finite ... ok`)
     - `tests/input_progress.rs`: 8 passed:
       * `all_segment_boundaries_preserve_unicode_and_control_interleaving ... ok`
       * `coalesced_complete_message_and_partial_extended_header_keep_distinct_ranges ... ok`
       * `fragmented_message_survives_ping_pong_and_coalesced_next_partial ... ok`
       * `idle_partial_header_payload_and_completion_have_exact_wire_offsets ... ok`
       * `offsets_include_mask_header_and_malformed_inputs_still_fail ... ok`
       * `partial_eof_remains_protocol_error_not_completed_frame ... ok`
       * `preloaded_handshake_tail_starts_at_websocket_zero_and_read_is_observational ... ok`
       * `progress_arithmetic_overflow_and_invalid_advance_are_sticky ... ok`
     - `tests/native_ws.rs`: 10 passed:
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
   - Total: **19 passed; 0 failed** in 1.92s.

2. **`owned-http` Cargo Test Suite (7 tests)**:
   - Command: `cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1"`
   - Output:
     - `src/lib.rs` / `src/ownership.rs`: 2 passed (`ownership::tests::exact_reversed_tuple_established_only_and_unique ... ok`, `tests::request_contract_is_finite_and_header_injection_is_rejected ... ok`)
     - `tests/native_http.rs`: 5 passed:
       * `allowed_post_duplicate_auth_and_local_validation_preserve_contract ... ok`
       * `malformed_oversized_ambiguous_redirect_truncated_and_extra_responses_fail_closed ... ok`
       * `owned_root_and_descendant_all_supported_framings ... ok`
       * `slow_trickle_cannot_extend_absolute_deadline ... ok`
       * `unrelated_established_listener_receives_no_http_bytes_and_survives ... ok`
   - Total: **7 passed; 0 failed** in 1.00s.

3. **Python Vendor Tamper Suite (`test_vendor_integrity.py`, 8 tests)**:
   - Command: `cmd.exe /c ".\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v"`
   - Output:
     - `test_exact_vendor_inventory_passes` PASSED
     - `test_modified_protocol_bytes_fail` PASSED
     - `test_extra_unlisted_file_fails` PASSED
     - `test_missing_file_fails` PASSED
     - `test_wrong_revision_fails` PASSED
     - `test_receipt_cannot_name_parent_path` PASSED
     - `test_receipt_cannot_omit_changed_file_patch` PASSED
     - `test_wrong_upstream_preimage_fails` PASSED
   - Total: **8 passed in 0.91s**.

4. **PowerShell Foundation Runner (`Verify-Foundation.ps1 -NativeFixtures`, 54 checks)**:
   - Pinned Upstream checkout at `G:\Personal_Assistant\hermes\hermes-agent` commit: `649d6c0391029f35959cfbc240eb3534a6667cf5`.
   - Command: `pwsh -NoProfile -Command ". .\.venv\Scripts\Activate.ps1; & hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -NativeFixtures"`
   - Result: Exit Code 0, **54 passed; 0 failed**.
   - Verified 4 new vendor gates in execution output:
     * `PASS owned-ws-vendor` (0.112s)
     * `PASS owned-ws-vendor-tests` (1.459s)
     * `PASS owned-ws-vendor-lint` (0.084s)
     * `PASS owned-ws-vendor-format` (0.087s)
   - Evidence file written: `hermes-native/.checks/verification.latest.json` with `"completed": true, "passed": true`.

5. **Desktop UI Truthful Reporting Verification**:
   - Inspected `hermes-native/apps/desktop-ui/src/host-adapter.ts`:
     * Line 46: `readonly binding: 'native-injected' | 'unavailable'`
     * Line 72: `if (disposed || !transport) return Promise.reject(new CapabilityUnavailableError(method))`
     * Line 88: `if (disposed || !transport) throw new CapabilityUnavailableError('events.${name}')`
     * Line 147: `binding: transport ? 'native-injected' : 'unavailable'`
   - Command: `node --test hermes-native/apps/desktop-ui/tests/host-adapter.test.mjs`
   - Output: **15 passed; 0 failed** in 81.65ms, specifically validating:
     * `no native transport cannot manufacture connection, model or version success`
     * `startup and recovery methods reject asynchronously with readable native denials`
     * `native event setup failure is observable and never masquerades as backend exit`

---

## 2. Logic Chain

1. **Preimage Conformance**: Worker M2 promoted `Verify-Foundation.ps1` from the verified candidate archive. Computing the SHA-256 sum confirms it matches `50c13008988d232279ee600b108b50da67ad6d8bcedaf065ce17e99fcc8b9230` without divergence or unauthorized additions.
2. **Strict Gate Enforcement**: The expanded script adds 4 vendor gates (`owned-ws-vendor`, `owned-ws-vendor-tests`, `owned-ws-vendor-lint`, `owned-ws-vendor-format`) to the foundation run. Each check invokes standard tools (`python verify_vendor.py`, `pytest`, `ruff check`, `ruff format --check`). `Invoke-Check` throws immediately if `$LASTEXITCODE -ne 0`, ensuring failure is never silently swallowed.
3. **Feature Coverage Completeness**: In `Verify-Foundation.ps1`, the conditional flags `if ($label -eq 'owned-ws') { $lintArgs += '--all-features' }` and `if ($label -eq 'owned-ws') { $testArgs += '--all-features' }` ensure that `test-fixture` is active during cargo test, enabling `tests/native_ws.rs` alongside `tests/input_progress.rs` and `src/lib.rs`.
4. **Transport Contract Conformance**:
   - `tests/input_progress.rs` (8 tests) verifies monotonic byte offset tracking in `InputProgress` and sticky error latching on overflow.
   - `tests/native_ws.rs` (10 tests) verifies bounded timeouts, credential scrubbing from logs, and clean separation between peer close and job retirement.
   - `tests/native_http.rs` (5 tests) and unit tests (2 tests) verify finite HTTP request contracts and bounded loopback interactions.
5. **UI Truthfulness Invariant**: The desktop UI host adapter explicitly defaults to `binding: 'unavailable'` when no native transport is injected, rejecting attempts to fake connection or model status with `HERMES_HOST_CAPABILITY_UNAVAILABLE`.

---

## 3. Adversarial Critic Challenge Analysis

### 3.1 Integrity Violation Assessment
- **Hardcoded test results**: None detected. Tests make live socket connections to loopback fixtures and verify real payloads and offsets.
- **Dummy/facade implementations**: None detected. `InputProgress`, `FrameProgress`, `OwnedWebSocket`, `host-adapter`, and `native-gateway-socket` contain full functional logic with robust edge-case validation.
- **Shortcuts/Bypasses**: None detected. The promotion was mandated by R1, and vendor verification enforces exact hashes across all 28 files.
- **Fabricated verification logs**: None detected. All commands were run independently in this review session with logs verified directly.
- **Self-certifying work**: None detected. Peer-close observation does not trigger host retirement; host retirement requires an explicit server acknowledgment receipt.

### 3.2 Assumption & Stress Test Results
1. **Assumption: Parser progress arithmetic never corrupts state on extreme wire inputs.**
   - *Test Scenario*: Injected `u64::MAX` to `FrameProgress.receive()`, `advance()`, and `increment()`.
   - *Observation*: `FrameProgress` catches overflow via `checked_add`, marks `self.failed = true`, and returns `Err(progress_error())`. All subsequent calls fail permanently.
   - *Result*: **PASS**.
2. **Assumption: Queued incoming messages are not discarded upon peer close.**
   - *Test Scenario*: Rapid peer close sent while incoming messages remain queued in `#incoming`.
   - *Observation*: `native-gateway-socket.ts` `#pumpReceive()` processes the entire queue before `#finish()` dispatches the close event.
   - *Result*: **PASS**.
3. **Assumption: Peer-initiated close does not prematurely kill or retire the worker process.**
   - *Test Scenario*: Peer closes connection; test checks worker process handle status before retirement.
   - *Observation*: `f.worker.worker().wait_timeout(Duration::ZERO)` returns `None` (process still running), confirming separation between remote protocol close and Windows process lifecycle.
   - *Result*: **PASS**.
4. **Assumption: Vendor tamper test catches subtle byte modifications or unlisted files.**
   - *Test Scenario*: Tamper suite tests modifying single bytes, inserting extra files, dropping files, altering receipt paths, and changing preimages.
   - *Observation*: All 8 tamper tests raise `ValueError` as expected.
   - *Result*: **PASS**.

---

## 4. Caveats

- **Pinned Upstream Commit**: `Verify-Foundation.ps1` requires `G:\Personal_Assistant\hermes\hermes-agent` at commit `649d6c0391029f35959cfbc240eb3534a6667cf5`. This dependency is currently satisfied.
- **Preexisting Dirty Files**: Baseline dirty files listed in `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json` remain untouched and intact.
- **No Other Caveats**: All test suites executed cleanly with zero warnings or failures.

---

## 5. Conclusion & Verdict

**Verdict**: **APPROVE**

Milestone 2 meets all acceptance criteria defined in `ORIGINAL_REQUEST.md` (## 2026-10-09T13:42:19Z) and `PROJECT.md`:
1. `Verify-Foundation.ps1` promoted to exact candidate preimage and expanded with 4 new vendor gates and `--all-features`.
2. All 19 `owned-ws` tests, 7 `owned-http` tests, 8 `input_progress` tests, and 8 vendor tamper tests pass cleanly.
3. Foundation verification script (`Verify-Foundation.ps1 -NativeFixtures`) completes with 54/54 passed check groups.
4. Desktop UI truthfully reports backend unavailable.
5. Zero integrity violations or facades detected.

Milestone 2 is formally verified and ready for Milestone 3 progression.

---

## 6. Verification Method

To independently reproduce this verification:

```powershell
# 1. Cargo test on owned-ws (19 tests)
cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-ws/Cargo.toml --all-features -- --test-threads=1 > ws_test.txt 2>&1"
# Inspect ws_test.txt (19 passed), delete log.

# 2. Cargo test on owned-http (7 tests)
cmd.exe /c "cargo test --manifest-path hermes-native/services/owned-http/Cargo.toml --all-features -- --test-threads=1 > http_test.txt 2>&1"
# Inspect http_test.txt (7 passed), delete log.

# 3. Python vendor tamper tests (8 tests)
cmd.exe /c ".\.venv\Scripts\python.exe -m pytest hermes-native/services/owned-ws/tests/test_vendor_integrity.py -v > vendor_test.txt 2>&1"
# Inspect vendor_test.txt (8 passed), delete log.

# 4. Foundation verification runner (54 checks)
pwsh -NoProfile -Command ". .\.venv\Scripts\Activate.ps1; & hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -NativeFixtures"

# 5. UI truthful host adapter test (15 tests)
cmd.exe /c "node --test hermes-native/apps/desktop-ui/tests/host-adapter.test.mjs > node_test.txt 2>&1"
# Inspect node_test.txt (15 passed), delete log.
```
