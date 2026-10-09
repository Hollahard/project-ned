# Milestone 4 Empirical Challenge Report — Job Object Containment, Concurrency & Proxy Loopback Stress (R4)

**Agent**: `m4_challenger_2`  
**Role**: EMPIRICAL CHALLENGER (critic, specialist)  
**Milestone**: Milestone 4 (Requirement R4)  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Workspace**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`  
**Date**: 2026-10-09T16:38:00Z  
**Verdict**: **REQUEST_CHANGES**  

---

## 1. Observation

### 1.1 Empirical Stress Test Harness (`apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs`)
An empirical adversarial test suite was authored and executed under `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1`:
```
running 5 tests
test test_environment_sanitization_adversarial_isolation_proof ... ok
test test_job_object_rapid_churn_stress ... ok
test test_job_object_strict_limit_flags_and_concurrency ... ok
test test_loopback_proxy_bypass_adversarial_poisoned_environment ... ok
test test_zero_orphans_post_execution_contract ... ok

test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.23s
```

### 1.2 Job Object Limit Flags & Concurrency Verification
- In `test_job_object_strict_limit_flags_and_concurrency`, direct Win32 API querying via `QueryInformationJobObject` with `JobObjectExtendedLimitInformation` verified:
  * `info.BasicLimitInformation.LimitFlags` contains `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`.
  * `info.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS (0x0008) == 0`.
  * `info.BasicLimitInformation.ActiveProcessLimit == 0` (unrestricted child worker concurrency).
  * `JOB_OBJECT_LIMIT_BREAKAWAY_OK` and `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK` are both `0` (breakaway strictly denied).
- Concurrency verification: 6 concurrent worker processes (`cmd.exe /c ping 127.0.0.1 -n 30`) were spawned and assigned to the Job Object. `query_active_process_count()` reported `>= 6`, and `contains_process` confirmed `true` for all 6 workers concurrently.
- Kill-on-close: Dropping the `JobObject` handle caused all 6 worker processes to be terminated immediately by the Windows kernel. `child.try_wait()` confirmed `Some(_)` for all 6 workers.

### 1.3 Rapid Churn & Zero Orphan Invariants
- `test_job_object_rapid_churn_stress`: Executed 10 consecutive cycles of Job Object creation, 2-worker assignment, and drop. All child processes were cleanly reaped with zero handle leaks.
- `test_zero_orphans_post_execution_contract`: Executed `cmd.exe /c "tasklist | findstr /i ping.exe"`, resulting in exit code `1` (0 orphaned ping processes).
- Clean system baseline: Executing `cmd.exe /c 'tasklist | findstr /i "ping.exe pytest.exe"'` returned exit code `1`, confirming zero orphaned test processes post-run.

### 1.4 Loopback Proxy Bypass Resilience
- In `test_loopback_proxy_bypass_adversarial_poisoned_environment`:
  * A mock HTTP server was bound to `127.0.0.1:<port>`.
  * Host environment proxy variables (`HTTP_PROXY`, `http_proxy`, `ALL_PROXY`, `all_proxy`) were explicitly set to a dead unrouteable proxy `http://127.0.0.1:1`.
  * A standard `reqwest::Client` without `.no_proxy()` failed to connect to `127.0.0.1:<port>/health` due to routing through the dead proxy.
  * `CoreProxy::new(port, ...)` (which configures `.no_proxy()` on `Client::builder()`) completely bypassed the dead proxy, successfully contacted `127.0.0.1:<port>/health`, and deserialized `HealthStatus` with 0 errors.

### 1.5 Multi-Cycle Stress Run Verification
1. `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1`:
   - 29/29 tests passed across all modules (`lib`, `test_job_object`, `test_sanitized_env`, `test_endurance_invariants`, `test_supervisor_soak`, `test_tokens`, `test_challenger_m4_tokens`, `test_challenger_m4_containment`).
2. `pytest tests/soak/test_adversarial_cli_lifecycle.py -v`:
   - 14/14 tests passed in 1.64s.
3. `pytest tests/soak/test_soak_endurance.py -v -m soak`:
   - 5/5 tests passed in 4.06s.
4. Preexisting dirty file hashes verification:
   - Evaluated `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`. All 4 baseline dirty files (`lib.rs`, `proxy.rs`, `tauri.conf.json`, `vite.config.ts`) remain 100% byte-identical.

### 1.6 Critical Vulnerability: Parent Environment Leak at OS Process Launch
- In `apps/desktop/src-tauri/src/processes.rs` lines 301–320 (`spawn_core`):
  ```rust
  let mut cmd = Command::new(python_exe);
  cmd.args([
      "-m",
      "uvicorn",
      "friday.api.app:create_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      &port.to_string(),
      "--log-level",
      "info",
  ])
  .current_dir(core_root)
  .envs(&sanitized)
  .stdin(Stdio::null())
  .stdout(Stdio::inherit())
  .stderr(Stdio::inherit());
  ```
- And lines 351–357 (`spawn_tabby`):
  ```rust
  let mut cmd = Command::new(python_exe);
  cmd.args(["main.py"])
      .current_dir(tabby_root)
      .envs(&sanitized)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit());
  ```
- **Empirical Observation**: In Rust `std::process::Command`, calling `.envs(&map)` does NOT clear the parent process's environment. Instead, it merges entries from `map` into the inherited parent environment.
- **Empirical Demonstration in `test_environment_sanitization_adversarial_isolation_proof`**:
  * Parent secrets were injected into the test process: `ADVERSARIAL_API_KEY`, `DATABASE_PASSWORD`, `PRIV_SSH_KEY`, `GIT_TOKEN`.
  * `build_sanitized_env(&extra, None)` correctly produced a HashMap containing only whitelisted variables.
  * Executing `Command::new("python.exe").envs(&sanitized)` resulted in the Python child process detecting parent secrets:
    `LEAK_DETECTED:ADVERSARIAL_API_KEY,DATABASE_PASSWORD,PRIV_SSH_KEY,GIT_TOKEN`.
  * Only when `cmd.env_clear()` was called before `cmd.envs(&sanitized)` did the child process execute with secrets stripped (`ISOLATED_OK`).

---

## 2. Logic Chain

1. **Job Object Containment**:
   - `JobObject::new()` configures `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` and omits `JOB_OBJECT_LIMIT_BREAKAWAY_OK` and `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`.
   - Observation 1.2 proves empirically that 6 concurrent processes execute inside the Job Object without hitting process count caps.
   - Closing or dropping the handle terminates all child processes, preventing process orphans.

2. **Loopback Proxy Bypass**:
   - When system/corporate proxy variables are present in the environment (`HTTP_PROXY`, `ALL_PROXY`), reqwest by default routes loopback traffic to the proxy, resulting in HTTP 400 or connection failure.
   - Observation 1.4 confirms that configuring `.no_proxy()` on `reqwest::Client::builder()` in `proxy.rs` successfully bypasses the proxy for loopback requests.

3. **Environment Sanitization Failure**:
   - Observation 1.6 shows that `build_sanitized_env()` filters environment variables in memory, but `spawn_core` and `spawn_tabby` invoke `Command::new` without calling `.env_clear()`.
   - In Rust `std::process::Command`, unless `.env_clear()` is explicitly invoked, the child process inherits the parent's environment block by default.
   - Consequently, host credentials, API keys, and shell secrets present in the supervisor process leak directly into the Core (`uvicorn`) and TabbyAPI child processes.
   - This violates Requirement R4 ("Sanitize child process environments by whitelisting only explicit variables... and stripping parent secrets") and Invariant 3 in `processes.rs` ("Child environment is an explicit whitelist. Never copy std::env::vars() wholesale").

---

## 3. Caveats

- In headless test execution, Win32 `GetForegroundWindow()` returns `NULL` when no foreground desktop window exists. This is safely handled by the fallback to headless mode in `approvals.rs`.
- No other caveats.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

- **Approved Subsystems**:
  * Windows Job Object Containment (`0x2000` kill-on-close, zero breakaway, clean drop reaping) is verified robust.
  * Child worker concurrency (`ActiveProcessLimit == 0`) is verified robust.
  * CoreProxy loopback bypass via `.no_proxy()` is verified robust.
  * Zero orphaned processes post-execution confirmed via `tasklist`.
  * Baseline dirty files preserved 100% byte-identically.

- **Required Change**:
  * In `apps/desktop/src-tauri/src/processes.rs`:
    Add `cmd.env_clear();` immediately before `cmd.envs(&sanitized);` in:
    1. `spawn_core` (around line 315)
    2. `spawn_tabby` (around line 354)
  * This guarantees that `CreateProcessW` receives strictly the sanitized whitelist without inheriting parent secrets.

---

## 5. Verification Method

To independently verify all findings and reproduce the vulnerability:

1. **Run Challenger Containment Test Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1 > test_out.log 2>&1"
   ```
   Inspect `test_out.log`: all 5 tests pass, including `test_environment_sanitization_adversarial_isolation_proof` proving the leak and the `.env_clear()` fix. Delete `test_out.log`.

2. **Verify Full Supervisor Test Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > cargo_full.log 2>&1"
   ```
   Inspect `cargo_full.log`: 29/29 tests pass. Delete `cargo_full.log`.

3. **Verify Adversarial CLI Lifecycle Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > pytest_adv.log 2>&1"
   ```
   Inspect `pytest_adv.log`: 14/14 tests pass. Delete `pytest_adv.log`.

4. **Verify Fast Soak Endurance Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > pytest_soak.log 2>&1"
   ```
   Inspect `pytest_soak.log`: 5/5 tests pass. Delete `pytest_soak.log`.

5. **Verify Zero Orphans via Tasklist**:
   ```cmd
   cmd.exe /c 'tasklist | findstr /i "ping.exe pytest.exe" > orphan_check.log 2>&1'
   ```
   Inspect: exit code 1 (no matches). Delete `orphan_check.log`.
