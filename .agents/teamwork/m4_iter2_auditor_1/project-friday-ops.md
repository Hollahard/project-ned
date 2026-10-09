# Project Friday Operational Runbook
Loaded from c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\skills\project-friday-ops\SKILL.md

Core methodology:
- Always run tests piped to temporary files through cmd.exe /c
- Pytest: cmd.exe /c ".\.venv\Scripts\pytest.exe ... > pytest_run.txt 2>&1"
- Rust: cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.txt 2>&1"
- Clean up temporary files immediately after inspection
