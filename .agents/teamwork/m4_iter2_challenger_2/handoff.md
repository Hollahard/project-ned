# Milestone 4 Iteration 2 Empirical Challenge Report — Job Object Containment & Environment Isolation Re-Challenge (R4)

**Agent**: `m4_iter2_challenger_2`  
**Role**: EMPIRICAL CHALLENGER (critic, specialist)  
**Milestone**: Milestone 4 Iteration 2 (Requirement R4)  
**Parent Agent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Workspace**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_challenger_2`  
**Date**: 2026-10-09T17:05:00Z  
**Verdict**: **APPROVE**  

---

## Challenge Summary

**Overall risk assessment**: **LOW (MITIGATED)**  
The parent environment leakage vulnerability identified during Milestone 4 Iteration 1 (`REQUEST_CHANGES`) has been completely and definitively resolved. Both `spawn_core` and `spawn_tabby` now explicitly call `.env_clear()` before applying `.envs(&sanitized)`, preventing ambient supervisor secrets and host environment variables from being passed to child processes. All empirical stress tests, isolation proofs, and regression suites passed with 100% success and zero orphaned processes.

---

## 1. Observation

### 1.1 Remediation in Source Code (`apps/desktop/src-tauri/src/processes.rs`)
Direct inspection of `apps/desktop/src-tauri/src/processes.rs` confirms the addition of `.env_clear()` to both process spawn sites:

1. `spawn_core` (lines 314–319):
   ```rust
   .current_dir(core_root)
   .env_clear()
   .envs(&sanitized)
   .stdin(Stdio::null())
   .stdout(Stdio::inherit())
   .stderr(Stdio::inherit());
   ```

2. `spawn_tabby` (lines 354–360):
   ```rust
   .current_dir(tabby_root)
   .env_clear()
   .envs(&sanitized)
   .stdin(Stdio::null())
   .stdout(Stdio::inherit())
   .stderr(Stdio::inherit());
   ```

### 1.2 Isolation Unit Test (`apps/desktop/src-tauri/tests/test_sanitized_env.rs`)
Inspection of `test_sanitized_env.rs` (lines 28–67) confirms the dedicated OS execution test `test_spawned_process_inherits_no_parent_secrets_with_env_clear`:
- Injects ambient mock secrets (`SUPERVISOR_PARENT_SECRET`, `ANTHROPIC_API_KEY`).
- Spawns `cmd.exe /c set` with `.env_clear().envs(&sanitized)`.
- Validates that stdout contains zero parent secrets, while correctly retaining whitelisted variables (`PATH`, `PYTHONUNBUFFERED=1`) and extra variables (`CHILD_TOKEN=token_123`).

### 1.3 Empirical Challenger Harness Re-Execution (`test_challenger_m4_containment.rs`)
Executed command:
```cmd
cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1 > m4_containment_run.txt 2>&1"
```
Log output:
```
running 5 tests
test test_environment_sanitization_adversarial_isolation_proof ... ok
test test_job_object_rapid_churn_stress ... ok
test test_job_object_strict_limit_flags_and_concurrency ... ok
test test_loopback_proxy_bypass_adversarial_poisoned_environment ... ok
test test_zero_orphans_post_execution_contract ... ok

test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.19s
```

All 5 empirical challenge tests passed:
- `test_environment_sanitization_adversarial_isolation_proof`: Proves empirically that `Command::new` without `.env_clear()` leaks parent secrets (`LEAK_DETECTED`), whereas invoking `.env_clear()` isolates the child process completely (`ISOLATED_OK`).
- `test_job_object_strict_limit_flags_and_concurrency`: Proves Win32 Job Object flags via `QueryInformationJobObject`:
  * `LimitFlags` has `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`.
  * `LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS (0x0008) == 0`.
  * `ActiveProcessLimit == 0` (unrestricted child worker concurrency).
  * `JOB_OBJECT_LIMIT_BREAKAWAY_OK == 0` and `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK == 0` (breakaway strictly denied).
  * 6 concurrent ping workers assigned and confirmed running; dropping Job Object reaped all 6 workers within deadline.
- `test_job_object_rapid_churn_stress`: 10 consecutive cycles of Job Object creation, 2-process assignment, and drop reaped cleanly.
- `test_loopback_proxy_bypass_adversarial_poisoned_environment`: CoreProxy configured with `.no_proxy()` successfully bypassed poisoned proxy environment (`HTTP_PROXY`, `ALL_PROXY` set to dead proxy) and queried loopback health endpoint.
- `test_zero_orphans_post_execution_contract`: Verified zero orphaned ping processes in system tasklist.

### 1.4 Full Cargo Test Suite Execution
Executed command:
```cmd
cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > m4_cargo_all_run.txt 2>&1"
```
Result:
```
test result: ok. 9 passed (lib.rs)
test result: ok. 0 passed (main.rs)
test result: ok. 5 passed (test_challenger_m4_containment.rs)
test result: ok. 9 passed (test_challenger_m4_tokens.rs)
test result: ok. 2 passed (test_endurance_invariants.rs)
test result: ok. 2 passed (test_job_object.rs)
test result: ok. 2 passed (test_sanitized_env.rs)
test result: ok. 3 passed (test_supervisor_soak.rs)
test result: ok. 2 passed (test_tokens.rs)
Total: 34 tests passed, 0 failed, 0 warnings
```

### 1.5 Cross-Stack Python Regression Suites
1. **Security Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > m4_pytest_sec.txt 2>&1"
   ```
   Result: `37 passed in 3.93s`

2. **Adversarial CLI Lifecycle Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > m4_pytest_adv.txt 2>&1"
   ```
   Result: `14 passed in 1.65s`

3. **Fast Soak Endurance Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > m4_pytest_soak.txt 2>&1"
   ```
   Result: `5 passed in 4.07s`

4. **Core Services Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -q > m4_pytest_core.txt 2>&1"
   ```
   Result: `210 passed in 19.50s`

### 1.6 Baseline Dirty File Preservation
Verified against `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`:
- `G:\Project_Ned\apps\desktop\src-tauri\src\lib.rs`: SHA256 match `True`
- `G:\Project_Ned\apps\desktop\src-tauri\src\proxy.rs`: SHA256 match `True`
- `G:\Project_Ned\apps\desktop\tauri.conf.json`: SHA256 match `True`
- `G:\Project_Ned\apps\desktop\vite.config.ts`: SHA256 match `True`
All 4 dirty files remain 100% byte-identical.

### 1.7 Zero Orphan Process Verification
Command:
```cmd
cmd.exe /c "tasklist | findstr /i \"ping.exe pytest.exe\""
```
Result: Exit code 1 (zero matching processes detected in Windows tasklist).

---

## 2. Logic Chain

1. In Rust `std::process::Command`, child processes inherit the parent's environment block by default unless `.env_clear()` is explicitly invoked prior to inserting sanitized variables.
2. In Milestone 4 Iteration 1, Observation 1.6 showed that `spawn_core` and `spawn_tabby` invoked `.envs(&sanitized)` without `.env_clear()`, causing parent secrets to leak into spawned Python processes.
3. Observations 1.1 and 1.2 demonstrate that `worker_m4_2` inserted `.env_clear()` directly into both `spawn_core` (line 315) and `spawn_tabby` (line 355), and added unit test coverage in `test_sanitized_env.rs`.
4. Observation 1.3 confirms via our empirical adversarial test harness (`test_environment_sanitization_adversarial_isolation_proof`) that calling `.env_clear()` before `.envs(&sanitized)` eliminates all secret leakage at the OS level while preserving required runtime variables (`PATH`, `TEMP`, `SYSTEMROOT`, `PYTHONUNBUFFERED`, `VIRTUAL_ENV`).
5. Observations 1.3 and 1.4 confirm that Job Object containment (`0x2000` kill-on-close, breakaway denial, and unrestricted child worker concurrency `ActiveProcessLimit == 0`) and `.no_proxy()` loopback bypass operate correctly under stress.
6. Observations 1.5, 1.6, and 1.7 confirm that the full system operates with zero regressions across 300+ tests, 100% byte-identical baseline file integrity, and zero orphaned OS processes.

---

## 3. Caveats

No caveats. All investigated areas passed empirical testing and meet all specification requirements under Requirement R4.

---

## 4. Conclusion

**Verdict: APPROVE**

- The environment sanitization vulnerability identified in Iteration 1 has been completely and cleanly resolved by adding `.env_clear()` in `apps/desktop/src-tauri/src/processes.rs`.
- Child processes (Core and TabbyAPI) are guaranteed to receive strictly the whitelisted environment variables without inheriting ambient host secrets.
- Job Object containment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000`, 0 active process limit, no breakaway) is verified robust across rapid churn and concurrency stress.
- All multi-stack test suites pass 100% with zero compiler warnings and zero orphaned processes.
- Milestone 4 is approved for progression to Milestone 5.

---

## 5. Verification Method

To independently verify all claims:

1. **Re-run Challenger Containment Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1 > test_out.log 2>&1"
   ```
   Inspect `test_out.log`: 5 passed in ~3.2s. Delete `test_out.log`.

2. **Re-run Full Supervisor Cargo Test Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > cargo_full.log 2>&1"
   ```
   Inspect `cargo_full.log`: 34 passed (across lib and integration tests), 0 warnings. Delete `cargo_full.log`.

3. **Re-run Security and Soak Suites**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > py_sec.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > py_adv.log 2>&1"
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > py_soak.log 2>&1"
   ```
   Inspect each log (37 passed, 14 passed, 5 passed). Delete logs.

4. **Verify Zero Orphan Processes**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i \"ping.exe pytest.exe\""
   ```
   Inspect exit code: 1 (no processes found).

5. **Verify Baseline Dirty File Hashes**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\python.exe -c ""import hashlib, json; [print(f['Path'], hashlib.sha256(open(f['Path'], 'rb').read()).hexdigest().upper() == f['Hash']) for f in json.load(open(r'G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json'))]"""
   ```
   Inspect: all 4 output lines report `True`.
