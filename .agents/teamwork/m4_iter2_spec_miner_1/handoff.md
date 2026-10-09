# Specification Mining Report & Milestone 4 Iteration 2 Handoff
## Process Environment Sanitization Invariants

**Agent**: `m4_iter2_spec_miner_1`  
**Role**: SPECIFICATION MINER (read-only, analytical)  
**Milestone**: Milestone 4 Iteration 2 (Process Sanitization Invariants)  
**Parent Agent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_iter2_spec_miner_1`  
**Date**: 2026-10-09T16:45:00Z  
**Verdict**: **SPECIFICATION_COMPLETE**

---

## 1. Observation

### 1.1 Process Spawning Implementation in `processes.rs`
In `apps/desktop/src-tauri/src/processes.rs`:
- Lines 301–320 (`ProcessManager::spawn_core`):
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

  let child = cmd.spawn()?;
  let pid = child.id();

  self.job_object.assign(&child)?;
  ```
- Lines 351–365 (`ProcessManager::spawn_tabby`):
  ```rust
  let mut cmd = Command::new(python_exe);
  cmd.args(["main.py"])
      .current_dir(tabby_root)
      .envs(&sanitized)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit());

  let child = cmd.spawn()?;
  let pid = child.id();

  self.job_object.assign(&child)?;
  ```
Direct inspection confirms that in both `spawn_core` and `spawn_tabby`, `cmd.env_clear()` is omitted. `cmd.envs(&sanitized)` is called directly on a newly created `Command` instance.

### 1.2 Environment Whitelist Builder (`processes.rs:174-223`)
In `apps/desktop/src-tauri/src/processes.rs`:
```rust
pub fn build_sanitized_env(
    extra: &HashMap<String, String>,
    venv_dir: Option<&Path>,
) -> HashMap<String, String> {
    const ALLOWED_VARS: &[&str] = &[
        "PATH",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    ];

    let mut env = HashMap::new();

    // Copy only whitelisted system variables
    for var in ALLOWED_VARS {
        if let Ok(val) = std::env::var(var) {
            env.insert(var.to_string(), val);
        }
    }

    // Configure virtual environment if provided
    if let Some(venv) = venv_dir {
        let venv_str = venv.to_string_lossy().to_string();
        env.insert("VIRTUAL_ENV".to_string(), venv_str.clone());
        let scripts_dir = venv.join("Scripts").to_string_lossy().to_string();
        if let Some(existing_path) = env.get("PATH").cloned() {
            env.insert("PATH".to_string(), format!("{};{}", scripts_dir, existing_path));
        } else {
            env.insert("PATH".to_string(), scripts_dir);
        }
    }

    // Always set Python unbuffered output
    env.insert("PYTHONUNBUFFERED".to_string(), "1".to_string());

    // Inject explicit extra variables (e.g. BEARER_TOKEN, ADMIN_KEY)
    for (k, v) in extra {
        env.insert(k.clone(), v.clone());
    }

    env
}
```
The whitelist filters variables into an in-memory `HashMap<String, String>`, but does not itself affect child process creation without OS-level clearing.

### 1.3 Empirical Proof of Leak in `test_challenger_m4_containment.rs`
In `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs` lines 243–288:
```rust
    // 4. Vulnerability Proof:
    // In Rust std::process::Command, calling .envs(&sanitized) WITHOUT .env_clear()
    // does NOT clear parent environment; it merges onto parent environment!
    // In processes.rs lines 315 and 354, Command::envs(&sanitized) is called without env_clear().
    let script = r#"
import os, sys
hostile_keys = ['ADVERSARIAL_API_KEY', 'DATABASE_PASSWORD', 'PRIV_SSH_KEY', 'GIT_TOKEN']
leaks = [k for k in hostile_keys if k in os.environ]
if leaks:
    print(f"LEAK_DETECTED:{','.join(leaks)}")
    sys.exit(10)
else:
    print("ISOLATED_OK")
    sys.exit(0)
"#;

    // Vulnerable invocation (as written in processes.rs lines 301-320 and 351-365)
    let vuln_output = Command::new("python.exe")
        .args(["-c", script])
        .envs(&sanitized)
        .output()
        .expect("Failed to execute python child process");

    let vuln_stdout = String::from_utf8_lossy(&vuln_output.stdout);
    assert!(
        vuln_stdout.contains("LEAK_DETECTED"),
        "Empirical proof: Command::envs without env_clear must reproduce the secret leak! Output: {}",
        vuln_stdout
    );

    // Secure invocation (with .env_clear())
    let mut secure_cmd = Command::new("python.exe");
    secure_cmd.env_clear();
    secure_cmd.envs(&sanitized);
    let secure_output = secure_cmd
        .args(["-c", script])
        .output()
        .expect("Failed to execute secure python child process");

    let secure_stdout = String::from_utf8_lossy(&secure_output.stdout);
    assert!(
        secure_stdout.contains("ISOLATED_OK"),
        "With env_clear(), secrets are properly isolated! Output: {}",
        secure_stdout
    );
```
Execution of `test_challenger_m4_containment` empirically verified that without `.env_clear()`, hostile parent environment variables leak into the child process.

### 1.4 Architectural Precedents & Existing Usages in Repo
- `docs/hermes-native-desktop/RECONCILIATION.md` line 28 explicitly documented this gap:
  > "Its `.envs(&sanitized)` calls at 315/354 also do not themselves clear the ambient process environment. An allowlisted map applied with `.envs` is therefore not equivalent to a fresh environment block."
- Existing native host tests in `hermes-native/services/control-host/tests/owned_control.rs` line 249 and `hermes-native/services/terminal-host/tests/conpty.rs` line 91 already implement `.env_clear()` before launching child fixtures.
- Python Core implementation in `services/core/src/friday/skills/cage.py` line 188 uses `os.environ` filtering passed to `subprocess.Popen(..., env=sanitized_env)`. In Python, `subprocess.Popen(..., env=dict)` replaces the process environment wholesale rather than merging.

---

## 2. Logic Chain

### 2.1 Contrast: Win32 `CreateProcessW` vs Rust `std::process::Command`

1. **Win32 `CreateProcessW` Environment Block Mechanics**:
   - Signature:
     ```c
     BOOL CreateProcessW(
         LPCWSTR lpApplicationName,
         LPWSTR lpCommandLine,
         LPSECURITY_ATTRIBUTES lpProcessAttributes,
         LPSECURITY_ATTRIBUTES lpThreadAttributes,
         BOOL bInheritHandles,
         DWORD dwCreationFlags,
         LPVOID lpEnvironment,        // <-- Environment block pointer
         LPCWSTR lpCurrentDirectory,
         LPSTARTUPINFOW lpStartupInfo,
         LPPROCESS_INFORMATION lpProcessInformation
     );
     ```
   - If `lpEnvironment == NULL`:
     The created child process inherits the environment block of the calling process verbatim.
   - If `lpEnvironment != NULL`:
     The child process receives **only** the variables contained in the supplied environment block. The calling process's ambient environment is completely bypassed.
   - Win32 Invariants for `lpEnvironment`:
     * Must be a null-delimited block of null-terminated strings (`Name=Value\0`), terminated by a final null character (`\0\0`).
     * When `CREATE_UNICODE_ENVIRONMENT (0x00000400)` is set in `dwCreationFlags`, characters must be 16-bit UTF-16LE (`wchar_t`).
     * Variable names must be sorted alphabetically in case-insensitive ordinal order (case-folded ASCII / `CompareStringOrdinal`).
     * Variable names are case-insensitive.

2. **Rust `std::process::Command` Environment Inheritance**:
   - In Rust's standard library (`std::sys::windows::process`):
     * `Command` encapsulates an internal environment mutation map `CommandEnv` with fields:
       `clear: bool` (default `false`) and `vars: BTreeMap<EnvKey, Option<OsString>>`.
     * **Default (Without `env_clear()`)**:
       When creating the environment block to pass to `CreateProcessW`, Rust starts by enumerating all variables from the parent process (`std::env::vars_os()`). It copies every parent variable into the child's block unless explicitly removed via `env_remove()`. It then overlays any additions from `.env()` or `.envs()`.
       **Result**: Calling `cmd.envs(&sanitized)` without `cmd.env_clear()` results in a set union:
       $$\text{ChildEnv} = \text{ParentEnv} \cup \text{Sanitized}$$
       All host secrets, cloud tokens, SSH keys, and shell variables survive and leak into the child process.
     * **With `env_clear()`**:
       Calling `cmd.env_clear()` sets `clear = true`.
       Rust completely skips copying `std::env::vars_os()`. It constructs the environment block strictly from the explicit key-value pairs added to `Command`.
       **Result**:
       $$\text{ChildEnv} = \text{Sanitized}$$
       Zero parent secrets leak into the child process.

3. **Contrast with Python `subprocess.Popen`**:
   - In Python, `subprocess.Popen(cmd, env=sanitized)` constructs a fresh environment block directly from `sanitized`. It does not merge with `os.environ` when `env` is provided.
   - Developers coming from Python may intuitively expect `cmd.envs(&map)` in Rust to behave like `env=map` in Python. In Rust, `env_clear()` is mandatory to achieve equivalent behavior.

---

### 2.2 Subsystem Requirements: The Windows Python Runtime Whitelist

If an environment is cleared via `env_clear()`, every omitted variable is absent. If required OS variables are missing, the Windows kernel, C Runtime (CRT), or Python interpreter will crash or malfunction. The following 12 variables in `ALLOWED_VARS` (`processes.rs:178-191`) are strictly necessary:

| Variable | Windows Subsystem / Runtime Purpose | Failure Mode if Omitted |
|---|---|---|
| `SYSTEMROOT` | Root directory of Windows (`C:\Windows`). Required by `ws2_32.dll` (Winsock) to locate network driver configs (`System32\drivers\etc\hosts`), and by CryptoAPI (`crypt32.dll`) to locate root certificates. Python `os.urandom()`, `socket`, `ssl`, and `ctypes` depend on this. | Winsock initialization latency/errors; TLS certificate validation crashes; `ctypes` failure to locate system DLLs. |
| `WINDIR` | Alias for `SYSTEMROOT`. Used by legacy Windows APIs, installers, and Python runtime shims. | Inconsistent Windows path resolution; package import crashes. |
| `SYSTEMDRIVE` | Drive letter of Windows system drive (`C:`). Used in expanding absolute system paths. | Failure in batch scripts and subprocess path expansions. |
| `PATH` | Dynamic-Link Library search path (`LoadLibraryExW`) and executable search path. Prepended with `<venv>\Scripts` by supervisor. | Python C-extensions (PyTorch `_C.pyd`, `sqlite3.pyd`, `uvicorn` native extensions) fail with `DLL load failed: The specified module could not be found`. |
| `TEMP` & `TMP` | Temporary directory paths. Used by Python `tempfile`, SQLite WAL journal temporary files, Uvicorn large body spooling, and PyTorch / Triton compilation caches. | `tempfile.gettempdir()` falls back to current workspace or `C:\Windows`, causing write permission denials or repository workspace pollution. |
| `COMSPEC` | Full path to `cmd.exe` (`C:\Windows\System32\cmd.exe`). Required by Python `subprocess.run(..., shell=True)` and `os.system()`. | Subprocess shell invocations fail with "executable not found". |
| `USERPROFILE` | Current user home directory (`C:\Users\<user>`). Required by Python `Path.home()` and `os.path.expanduser("~")`. PyTorch and Hugging Face store model weights and tokenizers under `%USERPROFILE%\.cache`. | `Path.home()` raises `RuntimeError: Could not determine home directory`. |
| `LOCALAPPDATA` | `%USERPROFILE%\AppData\Local`. Required for Windows local application data; Triton kernel compilation cache (`%LOCALAPPDATA%\triton\cache`). | Triton JIT compilation errors on NVIDIA RTX 5090 Blackwell runtime. |
| `APPDATA` | `%USERPROFILE%\AppData\Roaming`. User application settings and pip configuration cache. | Package dependency lookup errors and profile loading crashes. |
| `NUMBER_OF_PROCESSORS` | Total logical processor count. Polled by `os.cpu_count()`, OpenMP (`libgomp`/`vcomp140.dll`), Intel MKL, and PyTorch intra-op threads. | `os.cpu_count()` returns `None` or defaults to 1; parallel inference degrades to single-thread CPU execution. |
| `PROCESSOR_ARCHITECTURE` | System CPU architecture (`AMD64`). Checked by Python binary wheel loaders and PyTorch native architecture dispatches. | Binary wheel architecture incompatibility errors. |

#### Injected Runtime Parameters (Managed by Supervisor)
In addition to the 12 whitelisted OS variables, the supervisor injects:
1. `PYTHONUNBUFFERED="1"`: Enforces unbuffered stdout/stderr for real-time log ingestion.
2. `PYTHONPATH="<core_root>/src"`: Enables Python Core module imports.
3. `VIRTUAL_ENV="<venv_path>"`: Marks active virtual environment.
4. Process authentication credentials:
   - Core: `FRIDAY_BEARER_TOKEN`, `FRIDAY_PORT`
   - TabbyAPI: `TABBY_ADMIN_KEY`, `TABBY_PORT`

#### Prohibited / Stripped Host Secrets
The following classes of variables are strictly denied from child processes:
- LLM API keys: `ADVERSARIAL_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `HF_TOKEN`.
- Cloud credentials: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AZURE_CLIENT_SECRET`, `GOOGLE_APPLICATION_CREDENTIALS`.
- Git/SSH credentials: `GITHUB_TOKEN`, `GIT_TOKEN`, `PRIV_SSH_KEY`, `SSH_AUTH_SOCK`.
- Database credentials: `DATABASE_PASSWORD`, `DATABASE_URL`.

---

## 3. Features Discovered & Mined Specifications

```
## Features Discovered
| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Process Security | Win32 Clean Environment Block Injection | Pass non-NULL sorted double-null-terminated lpEnvironment to CreateProcessW with CREATE_UNICODE_ENVIRONMENT | Sorted UTF-16LE Key=Value buffer | Isolated child process PEB environment | If buffer not sorted or malformed, Win32 GetEnvironmentVariable behavior undefined | Win32 API specification & RECONCILIATION.md |
| 2 | Rust Subprocess | Command::env_clear Mandatory Invariant | In Rust Command, clear = true must be set to prevent inheriting std::env::vars_os() | None | Empty CommandEnv map | Without env_clear(), parent secrets merge with child environment | apps/desktop/src-tauri/src/processes.rs & test_challenger_m4_containment.rs |
| 3 | Environment Whitelist | OS Subsystem 12-Variable Whitelist | Whitelist strictly PATH, TEMP, TMP, SYSTEMROOT, SYSTEMDRIVE, WINDIR, COMSPEC, USERPROFILE, LOCALAPPDATA, APPDATA, NUMBER_OF_PROCESSORS, PROCESSOR_ARCHITECTURE | Ambient std::env::vars() | HashMap<String, String> | Missing variables crash Winsock, CryptoAPI, Triton, or OpenMP | processes.rs:178-191 & PROJECT.md |
| 4 | Virtualenv Routing | Child Virtualenv Path Prepending | Prepend <venv>/Scripts to PATH and inject VIRTUAL_ENV | venv_dir: Option<&Path> | Enhanced PATH and VIRTUAL_ENV in map | If venv missing, fallback to system PATH without prepending | processes.rs:203-212 |
| 5 | Child Telemetry | Python Unbuffered Output Invariant | Always inject PYTHONUNBUFFERED=1 into child environment | None | PYTHONUNBUFFERED=1 in env | If omitted, stdout buffers and supervisor misses real-time logs | processes.rs:215 |
| 6 | Sidecar Tokens | Ephemeral Process Token Injection | Pass single-use bearer tokens and ports via extra_env | extra: &HashMap<String, String> | FRIDAY_BEARER_TOKEN, TABBY_ADMIN_KEY injected | Reject invalid format; tokens expire after TTL | processes.rs:218-220 & PROJECT.md |
```

---

## 4. Edge Cases

```
## Edge Cases
| # | Feature | Input | Observed Behavior |
|---|---------|-------|-------------------|
| 1 | Case-Insensitive Var Names | Host has "Path" or "path" instead of "PATH" | On Windows, std::env::var("PATH") looks up case-insensitively; correctly extracts path value into uppercase "PATH" key. |
| 2 | Missing Whitelisted Variables | Optional system var (e.g., TMP or LOCALAPPDATA) missing from host environment | build_sanitized_env safely skips missing keys via `if let Ok(val) = std::env::var(var)` without panicking or creating empty keys. |
| 3 | Special Win32 Drive CWD Vars | Parent contains hidden drive variables like `=C:=C:\dir` | Rust env_clear() strips `=C:` variables. Child process relies on explicit Command::current_dir() (lpCurrentDirectory in CreateProcessW), ensuring reliable startup. |
| 4 | Unicode & Special Characters in Paths | Paths containing spaces or unicode (e.g. `C:\Users\Ghols\...`) | Win32 UTF-16LE encoding and OsString preservation cleanly support arbitrary Unicode paths without corruption. |
| 5 | Virtualenv Scripts Directory Missing | `venv_dir` provided but `venv/Scripts` does not exist | `venv.join("Scripts")` string is still prepended to PATH; python executable verification earlier in spawn_core/spawn_tabby catches missing binary with BinaryNotFound error. |
```

---

## 5. Pass/Fail Acceptance Criteria & Verification Commands

### 5.1 Acceptance Criteria for Milestone 4 Iteration 2

1. **Source Code Invariant**:
   - In `apps/desktop/src-tauri/src/processes.rs`:
     * `ProcessManager::spawn_core` MUST call `cmd.env_clear();` immediately prior to `cmd.envs(&sanitized);`.
     * `ProcessManager::spawn_tabby` MUST call `cmd.env_clear();` immediately prior to `cmd.envs(&sanitized);`.
2. **Empirical Process Isolation Invariant**:
   - Child processes spawned by `spawn_core` and `spawn_tabby` execute in a completely sanitized environment containing ONLY the 12 whitelisted system variables and the explicitly injected configuration/tokens.
   - Injecting hostile keys (`ADVERSARIAL_API_KEY`, `DATABASE_PASSWORD`, `PRIV_SSH_KEY`, `GIT_TOKEN`) into the supervisor process environment results in zero leaks to child processes.
3. **Regression Safety & Test Invariants**:
   - All 29 tests in `apps/desktop/src-tauri` pass cleanly with zero warnings:
     `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`
   - Python security suite passes 100%:
     `pytest tests/security/ -v`
   - Preexisting dirty file hashes in `G:\Project_Ned` remain 100% byte-identical to `preexisting-dirty-file-hashes.json`.
   - Zero orphaned processes post-execution (`tasklist | findstr /i ping.exe` returns exit code 1).

### 5.2 Verification Commands

All commands MUST follow GEMINI.md Rule 1 (routed via `cmd.exe /c` with log redirection):

1. **Rust Supervisor & Adversarial Containment Test Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1 > cargo_test_m4.txt 2>&1"
   ```
   *Expected output*: `test result: ok. 29 passed; 0 failed`. Inspect and delete `cargo_test_m4.txt`.

2. **Dedicated Challenger Containment Test**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_challenger_m4_containment -- --test-threads=1 > challenger_test.txt 2>&1"
   ```
   *Expected output*: `5 passed; 0 failed`. Inspect and delete `challenger_test.txt`.

3. **Python Security Test Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > pytest_sec.txt 2>&1"
   ```
   *Expected output*: `30 passed; 0 failed`. Inspect and delete `pytest_sec.txt`.

4. **Zero Orphaned Process Check**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i \"ping.exe pytest.exe\" > orphan_check.txt 2>&1"
   ```
   *Expected output*: Process returns exit code `1` (no matches found). Delete `orphan_check.txt`.

---

## 6. Caveats

- In headless CI/CD environments where desktop windows are not created, Win32 `GetForegroundWindow()` returns `0`, which is correctly supported by `approvals.rs` fallback logic.
- Rust's `Command::env_clear()` operates process-wide for the child being spawned; any custom variable intended for the child MUST be included in `sanitized` before `cmd.envs(&sanitized)` is called.
- No other caveats.

---

## 7. Conclusion

The specification mining for Milestone 4 Iteration 2 is complete. The root cause of the secret leak is the behavioral difference between Rust's `Command::envs()` (which merges with ambient parent variables) and Python's `subprocess.Popen(..., env=...)` (which replaces the environment block). To satisfy Requirement R4 and GEMINI.md Rule 2, calling `cmd.env_clear()` before `cmd.envs(&sanitized)` in `apps/desktop/src-tauri/src/processes.rs` (`spawn_core` and `spawn_tabby`) is strictly required and sufficient.

---

## 8. Verification Method

To independently verify the specification report:
1. View `apps/desktop/src-tauri/src/processes.rs` lines 301–365 to verify the absence of `env_clear()`.
2. View `apps/desktop/src-tauri/tests/test_challenger_m4_containment.rs` lines 243–288 to verify the empirical proof of leak vs isolation.
3. Execute `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` to verify existing baseline test passes.
