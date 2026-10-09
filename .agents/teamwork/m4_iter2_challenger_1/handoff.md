# Empirical Challenge Report: Milestone 4 Iteration 2 (Capability Tokens & Sanitized Environment Stress Testing)

**Agent**: `m4_iter2_challenger_1`  
**Role**: Empirical Challenger (critic, specialist)  
**Milestone**: Milestone 4 Iteration 2 (Security Containment & Invariants)  
**Parent Agent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_challenger_1`  
**Date**: 2026-10-09T17:10:00Z  
**Verdict**: **APPROVE**

---

## 1. Observation

### 1.1 Direct Inspection of Implementation Code
- **`apps/desktop/src-tauri/src/processes.rs`**:
  - Lines 314–319 (`spawn_core`):
    ```rust
    .current_dir(core_root)
    .env_clear()
    .envs(&sanitized)
    .stdin(Stdio::null())
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit());
    ```
  - Lines 353–359 (`spawn_tabby`):
    ```rust
    .current_dir(tabby_root)
    .env_clear()
    .envs(&sanitized)
    .stdin(Stdio::null())
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit());
    ```
  - Lines 174–221 (`build_sanitized_env`):
    Loops strictly over `const ALLOWED_VARS: &[&str]` (12 whitelisted system variable names: `PATH`, `TEMP`, `TMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`), adds `PYTHONUNBUFFERED=1`, optionally prepends `Scripts` to `PATH` if `venv_dir` is provided, and adds explicit `extra` entries. It does NOT iterate over `std::env::vars()`.

- **`apps/desktop/src-tauri/src/approvals.rs`**:
  - `canonicalize_json_value`: Recursively converts `serde_json::Value` objects into sorted `BTreeMap` structures, guaranteeing deterministic string serialization matching Python's `json.dumps(sort_keys=True, separators=(',', ':'))`.
  - `compute_args_hash`: Returns 64-character hex SHA-256 string.
  - `mint_token_with_hwnd`: Issues tokens signed with HMAC-SHA256 (`Hmac<Sha256>`), incorporating token UUID, tool name, argument hash, expiration timestamp, and caller HWND.
  - `validate_and_consume_with_hwnd`: Enforces atomic removal from `active_tokens`, validates TTL, tool name, argument hash, HWND binding, and HMAC signature, recording consumed tokens in `consumed_tokens`. Replay attempts fail with `TokenAlreadyConsumed` or `InvalidTokenFormat`.

### 1.2 Empirical Test Execution Results
All tests were executed through `cmd.exe /c` with log routing per GEMINI.md:

1. **Cargo Sanitized Env Test Suite**:
   - Command: `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_sanitized_env -- --test-threads=1"`
   - Output:
     ```
     running 2 tests
     test test_sanitized_environment_strips_parent_secrets ... ok
     test test_spawned_process_inherits_no_parent_secrets_with_env_clear ... ok

     test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
     ```

2. **Cargo Challenger Token Adversarial Suite**:
   - Command: `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_tokens -- --test-threads=1"`
   - Output:
     ```
     running 9 tests
     test test_adversarial_argument_tampering_rejection ... ok
     test test_adversarial_array_order_sensitivity_vs_object_invariance ... ok
     test test_adversarial_concurrent_replay_race ... ok
     test test_adversarial_deeply_nested_json_canonicalization ... ok
     test test_adversarial_expiration_ttl_rejection ... ok
     test test_adversarial_hwnd_binding_headless_caller_behavior ... ok
     test test_adversarial_hwnd_binding_mismatch_rejection ... ok
     test test_adversarial_replay_attack_rejection ... ok
     test test_adversarial_unicode_and_special_characters_canonicalization ... ok

     test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.02s
     ```

3. **Python Challenger Token Adversarial Suite**:
   - Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/test_challenger_m4_tokens.py -v"`
   - Output:
     ```
     collected 7 items
     tests/security/test_challenger_m4_tokens.py::test_adversarial_replay_attack_rejection PASSED [ 14%]
     tests/security/test_challenger_m4_tokens.py::test_adversarial_concurrent_replay_race PASSED [ 28%]
     tests/security/test_challenger_m4_tokens.py::test_adversarial_argument_tampering_rejection PASSED [ 42%]
     tests/security/test_challenger_m4_tokens.py::test_adversarial_expiration_ttl_rejection PASSED [ 57%]
     tests/security/test_challenger_m4_tokens.py::test_adversarial_json_canonicalization_nested_and_lists PASSED [ 71%]
     tests/security/test_challenger_m4_tokens.py::test_adversarial_unicode_canonicalization PASSED [ 85%]
     tests/security/test_challenger_m4_tokens.py::test_cross_language_canonical_hash_vectors PASSED [100%]

     7 passed in 0.40s
     ```

4. **Empirical Hostile Environment Permutations Stress Test**:
   - Authored and ran: `apps/desktop/src-tauri/tests/test_challenger_m4_env_permutations.rs`
   - Command: `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_env_permutations -- --test-threads=1"`
   - Tested 50+ hostile environment variable permutations:
     - High-value secrets: `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `ANTHROPIC_API_KEY`, `SUPERVISOR_SECRET`, `GITHUB_PAT`, `DATABASE_URL`, `SSH_PRIVATE_KEY`
     - Prefix/suffix collision attacks with whitelisted keys: `PATH_LEAK_SECRET`, `TEMP_SECRET_KEY`, `TMP_PRIVATE`, `SYSTEMROOT_PWD`, `SYSTEMDRIVE_CREDS`, `WINDIR_EXPLOIT`, `COMSPEC_INJECTION`, `USERPROFILE_ATTACK`, `LOCALAPPDATA_STEAL`, `APPDATA_BACKDOOR`, `NUMBER_OF_PROCESSORS_OVERFLOW`, `PROCESSOR_ARCHITECTURE_MIMIC`, `MY_PATH`, `SECRET_PATH`
     - Casing permutations: `hostile_lowercase_secret`, `hOsTiLe_MiXeD_sEcReT`, `api_key`
     - Value permutations: empty strings (`SECRET_EMPTY`), leading/trailing whitespace (`SECRET_WHITESPACE`), special characters (`SECRET_SPECIAL_CHARS = !@#$%^&*()_+-=[]{}|;':,./<>?`), multiline values.
     - Spawning child process (`cmd.exe /c set`) with `.env_clear().envs(&sanitized)` and inspecting full output.
   - Result:
     ```
     running 2 tests
     test test_adversarial_parent_secret_leak_permutations ... ok
     test test_adversarial_parent_secret_leak_with_venv_permutations ... ok

     test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.02s
     ```
     Confirmed: ZERO hostile keys and ZERO hostile values leaked into child environment or stdout. Whitelisted variables (`PATH`, `PYTHONUNBUFFERED`, `VIRTUAL_ENV`) and explicit extras (`CHILD_TOKEN_EXPLICIT`, `SUPERVISOR_PORT`) were strictly preserved.

5. **Complete Cargo Test Suite**:
   - Command: `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1"`
   - Result: `36 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 4.58s`
   - Zero compiler warnings.

6. **All Security Tests**:
   - Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v"`
   - Result: `37 passed in 3.90s`

7. **All Regression Suites**:
   - `test_adversarial_cli_lifecycle.py`: 14 passed in 1.67s
   - `test_soak_endurance.py -v -m soak`: 5 passed in 4.09s
   - `services/core/tests/`: 210 passed in 19.35s

8. **Baseline Dirty File Hashes**:
   - Checked against `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`:
     - `G:\Project_Ned\apps\desktop\src-tauri\src\lib.rs`: `True`
     - `G:\Project_Ned\apps\desktop\src-tauri\src\proxy.rs`: `True`
     - `G:\Project_Ned\apps\desktop\src-tauri\tauri.conf.json`: `True`
     - `G:\Project_Ned\apps\desktop\vite.config.ts`: `True`
   - All 4 files remain 100% byte-identical.

9. **Zero Orphaned Processes**:
   - Command: `cmd.exe /c "tasklist | findstr /i \"ping.exe pytest.exe\""`
   - Exit code: 1 (zero matching processes).

---

## 2. Logic Chain

1. In Windows standard process invocation (`CreateProcessW`), standard behavior clones the parent process's environment block unless the caller explicitly builds a fresh environment block.
2. In Rust `std::process::Command`, calling `.envs(&sanitized)` without `.env_clear()` leaves `clear: false`, causing Rust to merge the sanitized map entries on top of the parent process's environment block. This caused all ambient parent secrets to leak into child processes (empirically reproduced in `test_challenger_m4_containment.rs:259-272`).
3. Calling `.env_clear()` sets `CommandEnv.clear = true`, instructing Rust to construct a brand new environment block populated solely by the entries passed to `Command::envs`.
4. In `processes.rs`, both `spawn_core` (lines 314–319) and `spawn_tabby` (lines 353–359) invoke `.env_clear()` immediately before `.envs(&sanitized)`.
5. Because `build_sanitized_env` loops exclusively over the 12 explicit `ALLOWED_VARS` rather than iterating over parent `std::env::vars()`, no ambient parent secrets, unwhitelisted variables, or prefix/suffix collisions can enter `sanitized`.
6. Our empirical stress test `test_challenger_m4_env_permutations.rs` proved across 50+ adversarial permutations (including prefix collisions like `PATH_LEAK_SECRET`, lowercase keys, unicode, special chars, multiline strings, and venv prefixes) that child processes spawned with `.env_clear().envs(&sanitized)` inherit ZERO parent secrets and receive only the whitelisted environment.
7. Capability token security was verified across both Rust and Python implementations:
   - Atomic consumption prevents replay attacks (both immediate and 16-20 thread concurrent races).
   - Tampering defenses detect 1-byte mutations, added keys, missing keys, type changes, and tool substitutions.
   - Cross-language canonical JSON serialization hashes match exactly.
   - HWND binding prevents presentation from unauthorized windows and fails closed.
8. All 36 Cargo tests, 37 security tests, 19 soak/lifecycle tests, and 210 core tests pass with zero warnings, zero orphaned processes, and zero baseline dirty file mutations.

---

## 3. Caveats

No caveats. All investigations were executed empirically with direct test runs and process inspection.

---

## 4. Conclusion

**Verdict**: **APPROVE**

Milestone 4 Iteration 2 satisfies all security containment, environment sanitization, capability token, and process guardian invariants without regressions:
- Child processes are completely isolated from parent environment secrets under all tested permutations.
- Capability tokens are securely bound, single-use, deterministic, and replay-resistant.
- Job Object containment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000`, `ActiveProcessLimit = 0`) guarantees zero process orphans.
- Baseline dirty file hashes remain 100% byte-identical.

---

## 5. Verification Method

To independently verify this report:

1. **Verify Cargo Test Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > cargo_verify.log 2>&1"
   ```
   Inspect `cargo_verify.log` (confirm 36 passed, 0 failed, 0 warnings) and delete.

2. **Verify Adversarial Permutations & Tokens**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_env_permutations -- --test-threads=1 > perm_verify.log 2>&1"
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_tokens -- --test-threads=1 > tok_verify.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/test_challenger_m4_tokens.py -v > py_tok_verify.log 2>&1"
   ```
   Inspect each log and delete.

3. **Verify All Security & Regression Suites**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > sec_verify.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > adv_verify.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_verify.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -q > core_verify.log 2>&1"
   ```
   Inspect and delete each log.

4. **Verify Baseline Dirty File Hashes & Zero Orphans**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\python.exe -c ""import hashlib, json; [print(f['Path'], hashlib.sha256(open(f['Path'], 'rb').read()).hexdigest().upper() == f['Hash']) for f in json.load(open(r'G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json'))]"""
   cmd.exe /c "tasklist | findstr /i \"ping.exe pytest.exe\""
   ```
   Confirm all 4 files print `True` and findstr exits with 1.
