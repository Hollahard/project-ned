# Project Friday Operational Runbook

Use this skill to execute test suites, qualify local EXL3 models, and verify supervisor lifecycle invariants.

## 1. Multi-Stack Test Verification
Always run tests piped to a temporary file to ensure clean subshell termination on Windows:

### Python Core Test Suite
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/e2e/ -v > pytest_run.txt 2>&1"
```

### Rust Tauri Supervisor Test Suite
```cmd
cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.txt 2>&1"
```

### Desktop Contract Suite
```cmd
cmd.exe /c "npm --prefix apps/desktop test > npm_test.txt 2>&1"
```
