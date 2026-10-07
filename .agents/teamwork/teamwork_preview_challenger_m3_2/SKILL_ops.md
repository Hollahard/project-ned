---
name: project-friday-ops
description: >-
  Operational runbook for Project Friday testing, model qualification on the NVIDIA RTX 5090,
  and full multi-stack verification (Python Core, Rust Tauri Supervisor, and Desktop Contracts).
---

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

## 2. RTX 5090 Blackwell Qualification
- Runtime: `runtime/tabbyAPI` on `127.0.0.1:5000` with admin key.
- Pinned toolchain: PyTorch `2.11.0+cu130`, ExLlamaV3 `1.5.4+cu132.torch2.11.0`, Triton Windows `3.8.0.post29`.
- Stress Gate: Run 20 consecutive load/unload cycles to ensure 0 VRAM leaks:
```cmd
cmd.exe /c ".\.venv\Scripts\python.exe tests/qualification/test_20_cycles.py > cycles_out.txt 2>&1"
```
