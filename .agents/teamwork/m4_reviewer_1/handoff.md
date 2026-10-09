# Milestone 4 Review Report — Process Guardian & Security Containment Verification (Requirement R4)

**Reviewer**: `m4_reviewer_1`  
**Roles**: Reviewer (Correctness & Conformance), Critic (Adversarial Stress-Testing)  
**Milestone**: Milestone 4 (Requirement R4)  
**Parent**: `orchestrator_3` (Conversation ID: `635b9360-b27f-4ffc-82d0-46001e560e8d`)  
**Working Directory**: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\m4_reviewer_1`  
**Date**: 2026-10-09T16:26:00Z  

---

## Review Summary

**Verdict**: **APPROVE**  
**Integrity Violation Check**: **PASSED (0 violations detected)**  
**Adversarial Risk Assessment**: **LOW**

All requirements of Milestone 4 (Requirement R4) have been implemented correctly, securely, and without regressions. Independent test execution confirmed that all 19 supervisor Rust tests, 30 security tests, 14 adversarial lifecycle tests, 5 soak endurance tests, and 210 core regression tests pass cleanly. All 4 preexisting dirty files remain 100% byte-identical.

---

## 1. Observation

### 1.1 Reverse Proxy Loopback Configuration (`apps/desktop/src-tauri/src/proxy.rs`)
- **Direct Observation**:
  Line 170 of `apps/desktop/src-tauri/src/proxy.rs` configures the reqwest client with `.no_proxy()`:
  ```rust
  client: Client::builder().no_proxy().build().unwrap(),
  ```
- **Context & Impact**:
  Previously, default `Client::builder()` inherited system-wide corporate HTTP proxy settings, intercepting loopback calls (`127.0.0.1:<port>`) and returning HTTP 400 (`Direct IP access is not allowed`). Adding `.no_proxy()` guarantees loopback communication directly reaches the FastAPI Core service and TabbyAPI.

### 1.2 Win32 HWND Binding & Token Security (`apps/desktop/src-tauri/src/approvals.rs`)
- **Direct Observation**:
  - **HWND Resolution** (lines 74–82): `resolve_caller_hwnd() -> HWND` invokes `windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow()`, returning the caller's foreground `HWND` or `null_mut()` if unresolvable.
  - **Modal Binding** (lines 87–144): `show_native_approval_dialog_with_hwnd` explicitly passes `parent_hwnd` into `MessageBoxW` with flags `MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SYSTEMMODAL`. Default button is "No" (safe by default).
  - **ActiveTokenRecord** (lines 165–170): Tracks `tool_name: String`, `args_hash: String`, `expires_at: f64`, and `bound_hwnd: Option<isize>`.
  - **HMAC-SHA256 HWND Binding** (lines 245–253, 369–378):
    When `hwnd` is bound:
    `msg = format!("{}:{}:{}:{}:hwnd={}", token_id, tool_name, args_hash, expires_at, h)`
    HMAC is calculated using `Hmac<Sha256>` over `self.secret_key.as_bytes()`.
  - **Argument Hashing** (lines 46–70):
    `canonicalize_json_value` recursively sorts object keys via `BTreeMap`, ensuring identical output to Python's `json.dumps(sort_keys=True, separators=(',', ':'))`. Computes SHA-256 hash in hex.
  - **TTL & Single-Use Consumption** (lines 321–384):
    `validate_and_consume_with_hwnd`:
    1. Checks replay against `consumed_tokens: Arc<Mutex<Vec<String>>>` -> `TokenAlreadyConsumed`.
    2. Atomically removes from `active_tokens` -> preventing concurrent replay.
    3. Verifies `now <= record.expires_at` -> `TokenExpired`.
    4. Verifies `record.args_hash == current_args_hash` and `record.tool_name == tool_name` -> `ArgHashMismatch`.
    5. Verifies HWND binding: `if bound_h != ch` -> `CryptoError`.
    6. Recomputes and verifies HMAC-SHA256 signature.
    7. Appends to `consumed_tokens`.

### 1.3 Windows Job Object Containment & Sanitization (`apps/desktop/src-tauri/src/processes.rs`)
- **Direct Observation**:
  - **Kill-On-Job-Close** (lines 62–64):
    `info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;`
    Win32 constant `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is `0x2000`.
  - **Zero Breakaway**: `JOB_OBJECT_LIMIT_BREAKAWAY_OK` (0x0800) and `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK` (0x1000) are omitted. Child processes cannot detach.
  - **Unrestricted Concurrency**: `ActiveProcessLimit == 0` (omits `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`), allowing arbitrary concurrent child processes.
  - **Child Environment Sanitization** (lines 174–223):
    `build_sanitized_env` strictly whitelists:
    `PATH`, `TEMP`, `TMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`.
    Strips all unknown parent environment variables (API keys, credentials, tokens). Sets `PYTHONUNBUFFERED=1` and prepends `venv\Scripts` if virtual environment is supplied.

### 1.4 Independent Test Verification
Executed following GEMINI.md routing rules (`cmd.exe /c "..." > log.txt 2>&1`, inspected via `view_file`, immediately deleted):
- `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml`:
  **19 passed; 0 failed; finished in 0.90s**.
  - `apps/desktop/src-tauri/src/lib.rs`: 9 passed
  - `tests/test_endurance_invariants.rs`: 2 passed
  - `tests/test_job_object.rs`: 2 passed
  - `tests/test_sanitized_env.rs`: 1 passed
  - `tests/test_supervisor_soak.rs`: 3 passed
  - `tests/test_tokens.rs`: 2 passed
- `pytest tests/security/ -v`:
  **30 passed; 0 failed in 3.77s**.
- `pytest tests/soak/test_adversarial_cli_lifecycle.py -v`:
  **14 passed; 0 failed in 1.61s**.
- `pytest tests/soak/test_soak_endurance.py -v -m soak`:
  **5 passed; 0 failed in 3.98s**.
- `pytest services/core/tests/ -q`:
  **210 passed; 0 failed in 19.45s**.

### 1.5 Baseline Dirty File Hashes Verification
Executed against `G:\Project_Ned\.soak_workspace\preexisting-dirty-file-hashes.json`:
- `G:\Project_Ned\apps\desktop\src-tauri\src\lib.rs`: `5F779262B46E2AF882E28D3C43547840CCA16CAF7E64EB2CB907DFC2F46507A9` -> `True`
- `G:\Project_Ned\apps\desktop\src-tauri\src\proxy.rs`: `4BA5FDDA63C12F7275F81506D01B535A154259D2C0F0A2A132C377BEE505EDE3` -> `True`
- `G:\Project_Ned\apps\desktop\src-tauri\tauri.conf.json`: `1843E0D02AB9D344AACAB0B9292FE1E2AD1D98D700D77659612F52391D7EEED0` -> `True`
- `G:\Project_Ned\apps\desktop\vite.config.ts`: `D4F0ED4FE30358370157528C73510C8C1BF7644A8775345CEC22D90DBEB8B0AF` -> `True`
**Result**: 4 of 4 files (100%) match baseline hashes byte-for-byte.

---

## 2. Logic Chain

1. **Proxy Loopback Robustness**:
   - Reqwest by default inspects system and environment proxy variables.
   - When running on development or corporate machines where proxy variables are active, loopback requests to `127.0.0.1:<port>` are routed to external proxies, causing HTTP 400 errors.
   - Setting `.no_proxy()` on `Client::builder()` guarantees loopback requests to Core and TabbyAPI are routed directly to localhost, resolving proxy interception without modifying global environment variables.

2. **Win32 HWND Binding & Token Integrity**:
   - An unparented dialog (`NULL` HWND) can be occluded by external applications or orphaned in multi-window environments.
   - By resolving `GetForegroundWindow()` or passing an explicit `parent_hwnd`, dialogs are anchored to the calling window.
   - Capability tokens cryptographically incorporate the caller `HWND` into the HMAC-SHA256 message (`:hwnd=<h>`). An attacker cannot reuse or hijack a token from a different application window handle.
   - Enforcing canonical JSON hashing (`BTreeMap` recursion) guarantees identical hashes across Rust and Python (`sort_keys=True`).
   - Atomically removing tokens upon consumption prevents race conditions and ensures single-use invariants.

3. **Job Object Security Containment**:
   - Setting `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)` ensures the Windows NT kernel forcefully terminates all child processes when the supervisor process terminates or crashes.
   - Omitting breakaway flags prohibits child processes from detaching or creating background orphans.
   - Setting `ActiveProcessLimit == 0` ensures the Job Object does not artificially throttle worker concurrency.
   - Building environments strictly from an explicit whitelist guarantees parent secrets, cloud API keys, and credentials do not leak to child processes.

4. **Preservation of Preexisting Files**:
   - All 4 dirty baseline files in `G:\Project_Ned` were verified and remain 100% byte-identical to `preexisting-dirty-file-hashes.json`.

---

## 3. Adversarial Review & Integrity Audit

### 3.1 Integrity Violation Check
- **Hardcoded test results / expected outputs**: None found. Real cryptographic primitives (`HmacSha256`, `Sha256`, `Uuid::new_v4()`) and real Win32 APIs are used.
- **Dummy or facade implementations**: None found. All methods perform full validation and logic.
- **Shortcuts bypassing core work**: None.
- **Fabricated verification outputs**: None. All commands were independently executed and logged during this review.
- **Self-certifying work**: None.
- **Integrity Status**: **CLEAN (Zero Integrity Violations)**.

### 3.2 Adversarial Challenges & Mitigations
- **Challenge 1: Headless Execution & Null HWND**
  - *Scenario*: In CI or headless test execution, `GetForegroundWindow()` returns `NULL`.
  - *Mitigation*: `approvals.rs` gracefully accommodates `NULL` HWND when no foreground window exists, while strictly enforcing matching HWND whenever an explicit `HWND` is bound to the token. In soak test profiles, dangerous operations (Risk >= 2) are automatically denied without prompting modal dialogs, preventing headless CI hangs.
- **Challenge 2: Token Flooding / Memory DoS**
  - *Scenario*: An attacker could attempt to flood token minting to exhaust supervisor memory.
  - *Mitigation*: Line 223 in `approvals.rs` performs proactive pruning (`active.retain(|_, rec| now <= rec.expires_at)`) on every mint call, bounding memory strictly to unexpired tokens within the 120s TTL window.
- **Challenge 3: Child Process Breakaway**
  - *Scenario*: A child process attempts to call `CreateProcess` with `CREATE_BREAKAWAY_FROM_JOB`.
  - *Mitigation*: Because `JOB_OBJECT_LIMIT_BREAKAWAY_OK` is omitted, the kernel denies breakaway attempts with `ERROR_ACCESS_DENIED`, verified by red team test `test_vector_11_process_breakaway_and_job_object_containment`.

---

## 4. Verified Claims

| # | Claim | Verified Via | Result |
|---|-------|--------------|--------|
| 1 | `proxy.rs` configures `.no_proxy()` on `reqwest::Client::builder()` | Code inspection line 170 | PASS |
| 2 | `approvals.rs` binds `MessageBoxW` to Win32 `HWND` | Code inspection lines 87–128 | PASS |
| 3 | `ActiveTokenRecord` tracks tool, args hash, TTL, and bound HWND | Code inspection lines 165–170 | PASS |
| 4 | HMAC-SHA256 calculation incorporates caller HWND | Code inspection lines 246, 370 | PASS |
| 5 | Single-use consumption enforces replay rejection | `cargo test test_approval_manager_mint_and_single_use_consume`, `test_token_hwnd_binding_validation` | PASS |
| 6 | Argument canonicalization matches Python `sort_keys=True` | `cargo test test_canonicalize_json_value_sort_keys_parity`, `pytest test_capability_tokens.py` | PASS |
| 7 | Job Object enforces `0x2000` kill-on-close & permits concurrency | Code inspection lines 62–64, `cargo test test_job_object` | PASS |
| 8 | Child environment strips parent secrets | `cargo test test_sanitized_environment_strips_parent_secrets` | PASS |
| 9 | 19 supervisor Rust tests pass | `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml` (19/19 passed) | PASS |
| 10 | 30 security tests pass | `pytest tests/security/ -v` (30/30 passed) | PASS |
| 11 | Baseline dirty file hashes match 100% | SHA-256 validation against `preexisting-dirty-file-hashes.json` (4/4 matched) | PASS |
| 12 | No regressions in Core or Soak suites | `pytest services/core/tests/` (210 passed), `pytest tests/soak/test_soak_endurance.py` (5 passed), `pytest test_adversarial_cli_lifecycle.py` (14 passed) | PASS |

---

## 5. Caveats

- In headless test runs where no foreground GUI window exists, `GetForegroundWindow()` returns `NULL`. The implementation accommodates this by permitting headless execution while enforcing HWND verification whenever an explicit HWND is bound.
- No other caveats.

---

## 6. Conclusion

Milestone 4 (Requirement R4) satisfies all technical, architectural, and security acceptance criteria:
1. **Loopback Proxy**: Enforced via `.no_proxy()` in `proxy.rs`.
2. **Win32 HWND Binding**: Verified in `MessageBoxW` and `ApprovalManager`.
3. **Capability Tokens**: HMAC-SHA256 bound to caller HWND, single-use, 120s TTL, canonical JSON hashing.
4. **Job Object Containment**: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`, zero breakaway, unrestricted worker concurrency (`ActiveProcessLimit == 0`), clean environment sanitization.
5. **Dirty File Hashes**: 100% byte-identical preservation confirmed.
6. **Integrity & Test Regressions**: Zero integrity violations, 100% tests passing across all suites.

**Verdict: APPROVE.**

---

## 7. Verification Method

To reproduce and independently verify:
```cmd
:: 1. Verify Baseline Dirty File Hashes (must output all True)
cmd.exe /c ".\.venv\Scripts\python.exe -c ""import hashlib, json, pathlib; hashes = json.loads(pathlib.Path('G:/Project_Ned/.soak_workspace/preexisting-dirty-file-hashes.json').read_text()); results = [(h['Path'], hashlib.sha256(pathlib.Path(h['Path']).read_bytes()).hexdigest().upper() == h['Hash']) for h in hashes]; print(results); assert all(r[1] for r in results)"""

:: 2. Verify Rust Supervisor Tests (19 passed)
cmd.exe /c "cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.log 2>&1"
:: (view cargo_test.log, then del cargo_test.log)

:: 3. Verify Security Tests (30 passed)
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/security/ -v > pytest_sec.log 2>&1"
:: (view pytest_sec.log, then del pytest_sec.log)

:: 4. Verify Adversarial Lifecycle Tests (14 passed)
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_adversarial_cli_lifecycle.py -v > pytest_soak.log 2>&1"
:: (view pytest_soak.log, then del pytest_soak.log)

:: 5. Verify Soak Endurance Tests (5 passed)
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > pytest_endurance.log 2>&1"
:: (view pytest_endurance.log, then del pytest_endurance.log)

:: 6. Verify Full Core Suite (210 passed)
cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -q > pytest_core.log 2>&1"
:: (view pytest_core.log, then del pytest_core.log)
```
