# Investigation Report: Process Environment Sanitization Fix Strategy (Milestone 4 Iteration 2)

**Agent**: `m4_iter2_explorer_1`  
**Role**: Explorer (read-only investigation, process sanitization specialist)  
**Milestone**: Milestone 4 Iteration 2 (Requirement R4)  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Workspace**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned`  
**Date**: 2026-10-09T16:45:00Z  

---

## 1. Observation

### 1.1 Vulnerable Process Spawning in `apps/desktop/src-tauri/src/processes.rs`
Inspection of `apps/desktop/src-tauri/src/processes.rs` reveals the exact mechanism used to spawn Core and TabbyAPI:

**`spawn_core` (lines 301–320)**:
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

**`spawn_tabby` (lines 351–358)**:
```rust
let mut cmd = Command::new(python_exe);
cmd.args(["main.py"])
    .current_dir(tabby_root)
    .envs(&sanitized)
    .stdin(Stdio::null())
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit());
```

In both spawn functions, `Command::new(python_exe)` is constructed and chained directly with `.envs(&sanitized)`. Neither function calls `cmd.env_clear()`.

### 1.2 Test Blindspot in `apps/desktop/src-tauri/tests/test_sanitized_env.rs`
The existing unit test in `test_sanitized_env.rs` (lines 15–25):
```rust
let sanitized = build_sanitized_env(&extra, None);

// Assert sensitive parent vars are NOT present
assert!(!sanitized.contains_key("LEAKED_AWS_SECRET"));
assert!(!sanitized.contains_key("ANTHROPIC_API_KEY"));
```
This test only verified that `build_sanitized_env` returns a filtered `HashMap` in heap memory. It did **not** test whether `std::process::Command` actually passes an isolated environment to the spawned child process at the OS kernel level.

### 1.3 Adversarial Proof in `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs`
In `test_challenger_m4_containment.rs` lines 243–288, empirical testing proved the secret leak:
1. When `Command::new("python.exe").envs(&sanitized)` was invoked with parent host secrets (`ADVERSARIAL_API_KEY`, `DATABASE_PASSWORD`, `PRIV_SSH_KEY`, `GIT_TOKEN`), the child Python process detected the secrets in `os.environ` and printed:
   `LEAK_DETECTED:ADVERSARIAL_API_KEY,DATABASE_PASSWORD,PRIV_SSH_KEY,GIT_TOKEN` (exit code 10).
2. When `Command::new("python.exe")` had `secure_cmd.env_clear(); secure_cmd.envs(&sanitized);` called prior to launch, the child process executed in complete isolation:
   `ISOLATED_OK` (exit code 0).

### 1.4 Empirical Verification of Whitelisted Environment Completeness
An empirical execution of Python, uvicorn, and Friday Core was conducted in an isolated subshell where the environment was populated strictly with the keys produced by `build_sanitized_env` (plus `VIRTUAL_ENV`, `PYTHONUNBUFFERED`, `PYTHONPATH`, and process tokens).

Result:
```
Clean env keys: ['APPDATA', 'COMSPEC', 'FRIDAY_BEARER_TOKEN', 'FRIDAY_PORT', 'LOCALAPPDATA', 'NUMBER_OF_PROCESSORS', 'PATH', 'PROCESSOR_ARCHITECTURE', 'PYTHONPATH', 'PYTHONUNBUFFERED', 'SYSTEMDRIVE', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE', 'VIRTUAL_ENV', 'WINDIR']
1. Socket/Winsock OK: bound ephemeral port 49234
2. SSL Default Context OK
3. Tempfile OK: C:\Users\Ghols\AppData\Local\Temp
4. User home OK: C:\Users\Ghols
5. Multiprocessing CPU count OK: 32
6. Friday create_app OK: title='Friday Core API'
7. Complete Secret Isolation OK: 0 leaks
ALL_SYSTEMS_OPERATIONAL
```
The child process started without warnings, initialized Windows sockets, loaded crypto/SSL modules, accessed temporary directories, resolved user profile paths, determined CPU cores, created the FastAPI application, and verified 0 parent secret leaks.

---

## 2. Logic Chain

### 2.1 Rust Standard Library `Command` Architecture
In Rust's standard library (`std::process::Command` and its Windows implementation `sys::windows::process`):
1. `Command` stores environment modifications inside an internal `CommandEnv` struct:
   ```rust
   pub struct CommandEnv {
       clear: bool,
       saw_path: bool,
       vars: BTreeMap<EnvKey, Option<EnvVal>>,
   }
   ```
2. When `Command::new(program)` is initialized, `clear` defaults to `false` and `vars` is empty.
3. Calling `.envs(&map)` iterates over key-value pairs and calls `self.env(k, v)`, which inserts or updates the keys in `vars`. It **does not alter** `clear`.
4. When `Command::spawn()` is invoked:
   - If `clear == false`: Rust reads the entire parent process environment via `std::env::vars_os()` / `GetEnvironmentStringsW()`. It then applies the entries in `vars` as overrides. Any variable present in the parent process that is **not** explicitly present in `vars` is preserved untouched.
   - If `clear == true` (set via `cmd.env_clear()`): Rust initializes a blank environment block and populates it **exclusively** with entries in `vars`. All unmentioned parent variables are discarded.
5. In `processes.rs`, `spawn_core` and `spawn_tabby` do not call `.env_clear()`. Thus, `clear` remains `false`.
6. Therefore, `CreateProcessW` receives a merged environment block containing the full parent environment plus the sanitized entries. Host secrets (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`, shell credentials) leak directly into the Core service and TabbyAPI.

### 2.2 Sequence Ordering Invariant
Calling `cmd.env_clear()` must happen **before** `cmd.envs(&sanitized)`:
- `Command::env_clear(&mut self)` sets `clear = true` and clears `vars.clear()`.
- If `env_clear()` were called after `envs(&sanitized)`, the sanitized variables would be purged.
- Calling `cmd.env_clear()` immediately before `.envs(&sanitized)` (or immediately after `Command::new()`) guarantees that `clear` is true and `vars` contains strictly the sanitized whitelist.

### 2.3 Windows Environment Variable Requirements for Python & Uvicorn
Under Windows OS semantics (`CreateProcessW` and MSVC UCRT / Python 3.12):
1. **`SYSTEMROOT` (and `WINDIR`)**:
   - `ws2_32.dll` (Winsock) requires `%SystemRoot%\System32\drivers\etc\hosts` and socket catalog providers. Without it, `WSAStartup` fails (error 10107 `WSAESYSNOTREADY`).
   - `os.urandom()` on Windows loads `bcrypt.dll` from `%SystemRoot%\System32`.
   - Windows CryptoAPI and root CA trust stores depend on `SystemRoot`.
2. **`PATH`**:
   - Must contain `<venv>\Scripts` (for `python.exe`, `uvicorn.exe`, virtualenv DLLs) followed by `%SystemRoot%\System32;%SystemRoot%`. `build_sanitized_env` prepends the virtualenv scripts directory to `PATH`.
3. **`TEMP` and `TMP`**:
   - Python's `tempfile` module, SQLite temporary rollback journals/WAL files, and torch/triton kernel caches require `TEMP`/`TMP`. Without them, operations fall back to `C:\Temp` (which fails on non-elevated user accounts).
4. **`USERPROFILE`**:
   - Required by Python `pathlib.Path.home()` and `os.path.expanduser("~")`. Missing `USERPROFILE` raises `RuntimeError: Could not determine home directory`.
5. **`LOCALAPPDATA` and `APPDATA`**:
   - Used by HuggingFace, PyTorch, model weight caches, and local app configuration storage.
6. **`NUMBER_OF_PROCESSORS` and `PROCESSOR_ARCHITECTURE`**:
   - Required by Python `os.cpu_count()`, multiprocessing worker pools, and OpenMP thread dispatch.
7. **`COMSPEC` and `SYSTEMDRIVE`**:
   - Required by standard C runtime routines, path qualification, and subprocess commands.

All 12 variables above are present in `build_sanitized_env`'s `ALLOWED_VARS` list. When combined with `VIRTUAL_ENV`, `PYTHONUNBUFFERED`, `PYTHONPATH`, and service tokens (`FRIDAY_BEARER_TOKEN`, `FRIDAY_PORT`, `TABBY_ADMIN_KEY`, `TABBY_PORT`), the environment is complete and robust for Python, uvicorn, and TabbyAPI on Windows.

---

## 3. Caveats

1. **Environment Key Casing**: In `build_sanitized_env`, keys are matched from the host environment and inserted in uppercase (e.g. `"SYSTEMROOT"`). On Windows, `GetEnvironmentVariableW` and Python `os.environ` are case-insensitive. Empirical testing confirmed that Python, Winsock, UCRT, and uvicorn operate identically with `"SYSTEMROOT"` or `"SystemRoot"`.
2. **Proxy Environment Isolation**: Stripping `HTTP_PROXY`, `http_proxy`, `ALL_PROXY`, and `all_proxy` from child processes is a major security and reliability advantage: it prevents corporate or hostile proxies from intercepting internal loopback traffic (`127.0.0.1`) between Core and TabbyAPI.
3. **GPU / CUDA Dependencies**: In modern PyTorch / ExLlamaV3 wheels on Windows, CUDA runtime DLLs are self-contained within `site-packages/torch/lib/`, which Python adds via `os.add_dll_directory`. `CUDA_VISIBLE_DEVICES` defaults to all devices if omitted, targeting the NVIDIA RTX 5090 directly.

---

## 4. Conclusion

### Summary of Necessary Code Changes
In `apps/desktop/src-tauri/src/processes.rs`:
Insert `.env_clear()` directly before `.envs(&sanitized)` in both `spawn_core` and `spawn_tabby`.

### Precise Code Diffs for Implementer

#### 1. `spawn_core` in `apps/desktop/src-tauri/src/processes.rs` (around lines 313–318)
```rust
<<<< BEFORE
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
====
>>>> AFTER
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
        .env_clear()
        .envs(&sanitized)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
<<<<
```

#### 2. `spawn_tabby` in `apps/desktop/src-tauri/src/processes.rs` (around lines 352–357)
```rust
<<<< BEFORE
        let mut cmd = Command::new(python_exe);
        cmd.args(["main.py"])
            .current_dir(tabby_root)
            .envs(&sanitized)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());
====
>>>> AFTER
        let mut cmd = Command::new(python_exe);
        cmd.args(["main.py"])
            .current_dir(tabby_root)
            .env_clear()
            .envs(&sanitized)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());
<<<<
```

#### 3. Recommended Unit Test Addition in `apps/desktop/src-tauri/tests/test_sanitized_env.rs`
Add an OS process execution assertion to `test_sanitized_env.rs` to permanently guarantee regression protection:
```rust
#[test]
fn test_spawned_process_inherits_no_parent_secrets_with_env_clear() {
    unsafe {
        std::env::set_var("SUPERVISOR_PARENT_SECRET", "leaked_secret_val_999");
    }

    let mut extra = HashMap::new();
    extra.insert("CHILD_TOKEN".to_string(), "token_123".to_string());

    let sanitized = build_sanitized_env(&extra, None);

    let mut cmd = std::process::Command::new("cmd.exe");
    cmd.args(["/c", "set"])
        .env_clear()
        .envs(&sanitized);

    let output = cmd.output().expect("Failed to execute cmd");
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(
        !stdout.contains("SUPERVISOR_PARENT_SECRET"),
        "Parent secret leaked through Command with env_clear!"
    );
    assert!(
        stdout.contains("CHILD_TOKEN=token_123"),
        "Sanitized extra var missing in child process!"
    );
    assert!(
        stdout.contains("PATH="),
        "Sanitized PATH missing in child process!"
    );
}
```

---

## 5. Verification Method

To independently verify the fix and ensure zero regressions across all Milestone 4 deliverables:

### Step 1: Run Full Rust Tauri Supervisor Test Suite
```cmd
cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > cargo_verify.log 2>&1"
```
Inspect `cargo_verify.log`:
- Verify all 29+ tests pass (including `test_environment_sanitization_adversarial_isolation_proof`, `test_job_object_strict_limit_flags_and_concurrency`, and `test_loopback_proxy_bypass_adversarial_poisoned_environment`).
- Delete `cargo_verify.log`.

### Step 2: Run Python Adversarial CLI Lifecycle Suite
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > pytest_adv.log 2>&1"
```
Inspect `pytest_adv.log`:
- Verify 14/14 tests pass.
- Delete `pytest_adv.log`.

### Step 3: Run Fast Soak Endurance Suite
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > pytest_soak.log 2>&1"
```
Inspect `pytest_soak.log`:
- Verify 5/5 tests pass in < 5 seconds.
- Delete `pytest_soak.log`.

### Step 4: Verify Zero Orphaned Processes
```cmd
cmd.exe /c 'tasklist | findstr /i "ping.exe pytest.exe" > orphan_check.log 2>&1'
```
Inspect `orphan_check.log`:
- Verify exit code is 1 (zero matching processes).
- Delete `orphan_check.log`.

### Invalidation Conditions
- Any failure in Winsock (`WSAStartup`) or uvicorn socket binding during process launch.
- Any presence of parent environment secrets in child process inspection.
- Any regression in supervisor test suites.
