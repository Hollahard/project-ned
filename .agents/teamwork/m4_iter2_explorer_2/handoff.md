# Milestone 4 Iteration 2 Exploration Report — Repo-Wide Process Spawn & Environment Sanitization Audit

**Agent**: `m4_iter2_explorer_2`  
**Role**: EXPLORER (investigator, synthesizer)  
**Milestone**: Milestone 4 Iteration 2 (Requirement R4)  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_explorer_2`  
**Date**: 2026-10-09T16:46:00Z  

---

## 1. Observation

A repo-wide forensic audit of child process creation and environment handling was conducted across `apps/desktop/src-tauri/`, `hermes-native/`, and `services/core/`.

### 1.1 `apps/desktop/src-tauri/` (Rust Tauri Desktop Shell)

#### Observation 1.1.1: `apps/desktop/src-tauri/src/processes.rs`
- **`spawn_core` (lines 301–320)**:
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
- **`spawn_tabby` (lines 351–357)**:
  ```rust
  let mut cmd = Command::new(python_exe);
  cmd.args(["main.py"])
      .current_dir(tabby_root)
      .envs(&sanitized)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit());
  ```
- **`reap_stale_port` (lines 228–254)**:
  ```rust
  let output = Command::new("netstat")
      .args(["-ano", "-p", "tcp"])
      ...;
  let _ = Command::new("taskkill")
      .args(["/F", "/PID", &pid.to_string()])
      ...;
  ```
- **Defect Observation**: In Rust `std::process::Command`, calling `.envs(&sanitized)` does **not** clear existing parent environment variables. It merely merges the entries in `&sanitized` into the inherited environment block. Without an explicit `.env_clear()`, all parent secrets (e.g. `ADVERSARIAL_API_KEY`, `DATABASE_PASSWORD`, host SSH tokens) are passed to `uvicorn` and TabbyAPI.
- **Diagnostic Tools**: `reap_stale_port` invokes `netstat` and `taskkill` with fixed argument vectors to clean up dead listeners; these are non-service diagnostic utilities that do not execute arbitrary user code or intend to be caged.

#### Observation 1.1.2: Other files in `apps/desktop/src-tauri/src/`
- `runtime.rs`: Lines 103 and 121 invoke `proc_mgr.spawn_tabby` and `proc_mgr.spawn_core`. Contains zero direct process spawning.
- `commands.rs`, `approvals.rs`, `proxy.rs`, `first_launch.rs`, `lib.rs`: Contain zero OS process spawning (`tauri::async_runtime::spawn` in `lib.rs:30` is an in-process Tokio task).

#### Observation 1.1.3: Tests in `apps/desktop/src-tauri/tests/`
- `test_challenger_m4_containment.rs` lines 260–288:
  Authored by `m4_challenger_2`. Empirically demonstrates that `Command::new("python.exe").envs(&sanitized)` leaks parent environment variables (`LEAK_DETECTED`), whereas `Command::new("python.exe").env_clear().envs(&sanitized)` isolates the child (`ISOLATED_OK`).

---

### 1.2 `hermes-native/` (Native Transports and Microservices)

#### Observation 1.2.1: `hermes-native/services/resource-host/`
- **`src/windows.rs` (lines 148–178, `spawn_native`)**:
  ```rust
  let mut environment = environment_block(&spec.environment)?;
  ...
  let created = unsafe {
      CreateProcessW(
          application.as_ptr(),
          command.as_mut_ptr(),
          null(),
          null(),
          inherit_handles,
          CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | extra_flags,
          environment.as_mut_ptr() as *const c_void,
          directory.as_ptr(),
          startup_ptr,
          &mut information,
      )
  };
  ```
- **`src/windows.rs` (lines 417–442, `environment_block`)**:
  Builds a double-NUL-terminated UTF-16 environment block solely from `spec.environment: BTreeMap<String, OsString>`.
- **`src/windows.rs` (lines 30–37, `WorkerSpec`)**:
  `/// Explicit inputs only: no inherited environment, shell expansion or PATH lookup.`
- **Win32 Semantics**: When `CreateProcessW` receives a non-NULL `lpEnvironment` pointer with `CREATE_UNICODE_ENVIRONMENT`, Windows uses **only** the provided environment buffer. It does **not** inherit the parent environment block.
- **`tests/owned_workers.rs` (lines 111–115)**:
  Directly asserts that parent environment variables are never inherited:
  ```rust
  assert!(!keys.iter().any(
      |key| ["VIRTUAL_ENV", "PATH", "OPENAI_API_KEY", "TABBY_API_KEY"].contains(&key.as_str())
  ));
  ```
- **Test Fixtures**: `src/bin/worker_fixture.rs` lines 107 & 149 spawn dummy sleep processes to test Job Object tree capture. `tests/owned_workers.rs:133` and `tests/captured_workers.rs:133` spawn unassigned `sleep` processes to test isolation boundaries.

#### Observation 1.2.2: `hermes-native/services/backend-host/`
- **`src/hermes_backend_host/windows_process.py` (lines 263–275)**:
  Direct Win32 `CreateProcessW` ctypes call passing `env = environment_block(environment)` with flags `0x08000000 | 0x00000400 | 0x00080000` (`CREATE_UNICODE_ENVIRONMENT`). Lines 162–177 construct the double-NUL-terminated buffer strictly from the passed dictionary. Parent variables are never inherited.

#### Observation 1.2.3: `hermes-native/services/terminal-host/`
- **`src/lib.rs` (lines 243–259, `Terminal::spawn`)**:
  Direct Win32 `CreateProcessW` passing `environment = environment_block(&spec.environment)?;` and `CREATE_UNICODE_ENVIRONMENT`.
- **`tests/conpty.rs` (lines 88–98)**:
  Spawns an unrelated test fixture using `std::process::Command` and **already explicitly calls `.env_clear()`**:
  ```rust
  let mut unrelated = OwnedFixture(
      Command::new(env!("CARGO_BIN_EXE_terminal-fixture"))
          .arg("--idle")
          .env_clear()
          .env("SystemRoot", std::env::var("SystemRoot").unwrap())
          ...
  );
  ```
- **`tests/conpty.rs` (lines 207–210)**:
  Asserts `text.contains("ENV_COUNT:2"), "parent environment must not be inherited"`.

#### Observation 1.2.4: `hermes-native/services/control-host/`
- Delegates worker spawning to `hermes-resource-host` (see `Cargo.toml:9`).
- **`tests/owned_control.rs` (lines 246–256)**:
  Spawns an unrelated fixture using `std::process::Command` and **already explicitly calls `.env_clear()`**:
  ```rust
  let mut unrelated = Unrelated(
      Command::new(env!("CARGO_BIN_EXE_control-peer-fixture"))
          .current_dir(&unrelated_state.state)
          .env_clear()
          .stdin(Stdio::null())
          ...
  );
  ```

#### Observation 1.2.5: `hermes-native/services/catalog-host/`
- Delegates worker spawning to `hermes-resource-host` (see `Cargo.toml:9`).
- `tests/owned_catalog.rs:251`: Spawns an outsider test process (`Command::new(python()).args(["-I", "-S", "-B", "-c", "..."])`) to verify that terminating the Job Object does not affect outsider processes.

#### Observation 1.2.6: `hermes-native/services/owned-ws/` and `owned-http/`
- `tests/fixtures/server.rs:56`: Internal test fixture binary spawning a descendant in `"descendant"` test mode.

---

### 1.3 `services/core/` (Python Core Service)

#### Observation 1.3.1: `services/core/src/friday/skills/cage.py` & `supervisor.py`
- **`cage.py` (lines 185–203, `get_sanitized_cage_env`)**:
  Filters `os.environ` against `SAFE_CAGE_ENV_WHITELIST` (`SYSTEMROOT`, `SYSTEMDRIVE`, `PATH`, `TEMP`, `TMP`, `PYTHONPATH`, `PYTHONHOME`, `WINDIR`), sets isolated `PYTHONPATH`, and overrides `TEMP`/`TMP` to the clean temp directory.
- **`supervisor.py` (lines 78–85, `SkillHostSupervisor.start`)**:
  ```python
  self._process = subprocess.Popen(
      cmd,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=str(self._temp_dir),
      env=sanitized_env,
  )
  ```
- **Python `subprocess` Semantics**:
  In Python's `subprocess.Popen(..., env=env)` and `asyncio.create_subprocess_exec(..., env=env)`, passing `env` does **not** merge with `os.environ`. The Python standard library converts the dictionary into an explicit Windows environment block and passes it to `CreateProcessW`, **completely replacing** the parent environment. Parent variables not present in `sanitized_env` are never passed to the child process.

#### Observation 1.3.2: `services/core/src/friday/tools/terminal_exec.py`
- **Lines 70–77 (`get_sanitized_env`)**: Filters `os.environ` against `SAFE_ENV_WHITELIST`.
- **Lines 133–139**:
  ```python
  proc = await asyncio.create_subprocess_exec(
      *exec_args,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
      cwd=str(cwd_path),
      env=env,
  )
  ```
- Operates under Python's environment replacement semantics; parent secrets are stripped.

#### Observation 1.3.3: Other `subprocess` calls in `services/core/`
- `friday/security/powershell.py:210`: `subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parser_ps], input=command, ...)` runs an internal PowerShell AST parsing validator on script strings. Does not execute user code or handle untrusted child environments.
- `friday/tools/native_read.py:205`: `subprocess.run(["git", "diff", ...])` is an internal read-only tool helper.
- `friday/storage/checkpoints.py:56`: `subprocess.run(["git", "hash-object", "-w", str(target)], ...)` creates loose git blobs for pre-write rollbacks.

---

## 2. Logic Chain

1. **Root Vulnerability Mechanism**:
   - In Rust's `std::process::Command`, the environment map is initialized as a clone of the parent process's environment. Calling `.envs(&map)` iterates over `map` and sets or overwrites key-value pairs in the command's existing environment map. It does **not** delete keys that are present in the parent but absent from `map`.
   - The only way to clear the inherited parent environment in Rust `std::process::Command` is to call `.env_clear()`.

2. **Scope of Rust `Command::new` in the Repo**:
   - A repo-wide grep for `Command::new` identified 14 files:
     * 5 files in `apps/desktop/src-tauri/` (`processes.rs`, 4 test files).
     * 9 files in `hermes-native/` (all either test suites, test fixtures, or test helper binaries).
   - In `apps/desktop/src-tauri/src/processes.rs`:
     * `spawn_core` and `spawn_tabby` both invoke `cmd.envs(&sanitized)` without `cmd.env_clear()`.
     * As observed in 1.1.1 and proven in 1.1.3, this causes all supervisor environment secrets to be inherited by Core and TabbyAPI.
     * `reap_stale_port` runs `netstat` and `taskkill` which are short-lived diagnostic commands and not persistent child service containers.

3. **Comparison with `hermes-native/` Microservices**:
   - As observed in 1.2.1, 1.2.2, and 1.2.3, the production process-spawning components of `hermes-native` (`resource-host`, `backend-host`, `terminal-host`) do **not** use `std::process::Command`.
   - Instead, they call Win32 `CreateProcessW` directly, passing `CREATE_UNICODE_ENVIRONMENT` and an explicit double-NUL-terminated buffer (`environment_block`).
   - Win32 API rules mandate that when a custom environment block is passed to `CreateProcessW`, the child process inherits **zero** environment variables from the parent process.
   - The host services (`control-host`, `catalog-host`) delegate all worker lifecycle to `resource-host`.
   - Furthermore, test suites in `control-host/tests/owned_control.rs:249` and `terminal-host/tests/conpty.rs:91` that use `std::process::Command` **already call `.env_clear()`**.
   - Therefore, `hermes-native/` is completely immune to this vulnerability and requires no changes.

4. **Comparison with `services/core/` (Python)**:
   - As observed in 1.3.1 and 1.3.2, Python's `subprocess.Popen` and `asyncio.create_subprocess_exec` in `cage.py`/`supervisor.py` and `terminal_exec.py` pass a sanitized dictionary to `env=...`.
   - Unlike Rust's `Command`, Python's `subprocess` does **not** merge `env` with `os.environ`; it replaces the environment entirely.
   - Therefore, `services/core/` already guarantees full environment isolation and requires no changes.

5. **Exclusivity of the Defect**:
   - Because `hermes-native` uses direct Win32 `CreateProcessW` with explicit blocks, and `services/core` uses Python's replacement-semantics `env=...`, the defect where an intended whitelist is merged rather than isolated exists **exclusively** in `apps/desktop/src-tauri/src/processes.rs`.

---

## 3. Caveats

- **Test Fixture Binaries**: Test fixture binaries in `hermes-native` (e.g. `worker_fixture.rs`, `terminal-fixture.rs`, `server.rs`) spawn dummy descendant processes (such as `sleep`) using `Command::new` without `.env_clear()`. These are test-only stubs conditionally compiled under `#[cfg(feature = "test-fixture")]` used to test Job Object tree capture; they are not production code and handle no sensitive data.
- No other caveats.

---

## 4. Conclusion

- **Definitive Finding**:
  The defect is **confined exclusively to `apps/desktop/src-tauri/src/processes.rs`**.
  Zero other production files across `hermes-native/` or `services/core/` require adjustment.

- **Required Action for the Implementer Agent**:
  In `apps/desktop/src-tauri/src/processes.rs`:
  Add `cmd.env_clear();` immediately prior to `cmd.envs(&sanitized);` in:
  1. `spawn_core` (before line 315)
  2. `spawn_tabby` (before line 354)

- **Snippet of the Proposed Change**:
  ```rust
  // In apps/desktop/src-tauri/src/processes.rs spawn_core:
  let mut cmd = Command::new(python_exe);
  cmd.args([ ... ])
      .current_dir(core_root)
      .env_clear()            // <--- ADD THIS
      .envs(&sanitized)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit());

  // In apps/desktop/src-tauri/src/processes.rs spawn_tabby:
  let mut cmd = Command::new(python_exe);
  cmd.args(["main.py"])
      .current_dir(tabby_root)
      .env_clear()            // <--- ADD THIS
      .envs(&sanitized)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit());
  ```

---

## 5. Verification Method

To independently verify the audit conclusions:

1. **Verify `hermes-native/services/resource-host` Environment Isolation**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path hermes-native/services/resource-host/Cargo.toml --features test-fixture --test owned_workers -- --test-threads=1 > resource_host_test.log 2>&1"
   ```
   Inspect `resource_host_test.log`: Verify `child_receives_literal_unicode_arguments_and_only_explicit_environment` passes, proving parent environment variables are never inherited. Delete `resource_host_test.log`.

2. **Verify `hermes-native/services/terminal-host` Environment Isolation**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path hermes-native/services/terminal-host/Cargo.toml --features test-fixture --test conpty -- --test-threads=1 > terminal_host_test.log 2>&1"
   ```
   Inspect `terminal_host_test.log`: Verify `argument_quoting_and_explicit_environment_survive_native_process_creation` passes, confirming `ENV_COUNT:2` and zero parent environment leakage. Delete `terminal_host_test.log`.

3. **Verify `services/core` Skill Cage Isolation**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/test_skills_part_b.py -v > skill_cage_test.log 2>&1"
   ```
   Inspect `skill_cage_test.log`: Verify all caged skill host tests pass with isolated environment tables. Delete `skill_cage_test.log`.

4. **Verify Desktop Challenger Isolation Proof**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1 > containment_test.log 2>&1"
   ```
   Inspect `containment_test.log`: Verify `test_environment_sanitization_adversarial_isolation_proof` proves that `.env_clear()` before `.envs(&sanitized)` eliminates the leak. Delete `containment_test.log`.

5. **Verify Baseline Dirty File Hashes**:
   Compare hashes against `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json` to verify that `lib.rs`, `proxy.rs`, `tauri.conf.json`, and `vite.config.ts` remain 100% byte-identical.
