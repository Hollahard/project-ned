# Project Friday Operational Runbook (Local Copy)

Source: g:\Project_Ned\.agents\skills\project-friday-ops\SKILL.md

## Multi-Stack Test Verification
Always run tests piped to a temporary file to ensure clean subshell termination on Windows:
- Python Core Test Suite: `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/e2e/ -v > pytest_run.txt 2>&1"`
- Rust Tauri Supervisor Test Suite: `cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.txt 2>&1"`
- Desktop Contract Suite: `cmd.exe /c "npm --prefix apps/desktop test > npm_test.txt 2>&1"`
