# Project Friday (Project Ned) — Workspace Rules

## 1. Terminal Execution & Subshell Invariants
- **Always Route Tests to Output Files**: When running test or build commands (`pytest`, `cargo test`, `npm test`), always route through `cmd.exe /c` or pipe output to a temporary log file (`> log.txt 2>&1`) and inspect via `view_file`.
  - Example: `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ -v > pytest_run.txt 2>&1"`
  - Immediately delete temporary test output logs after inspection.
- **PowerShell Parentheses Escaping**: When passing paths with `(x86)` or commit messages with parentheses like `feat(core): ...`, always quote strings or escape them in pwsh to avoid subexpression evaluation errors.
- **Sandbox Bypass**: Workspaces spanning drive G: with restricted system drives require `BypassSandbox: true` for reliable execution.

## 2. Process Guardian & Sidecar Invariants
- **Zero Orphaned Processes**: Child processes (Core and TabbyAPI) must run inside the Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Breakaway is strictly denied.
- **Environment Sanitization**: Never copy `std::env::vars()` or `os.environ` wholesale to child processes. Strip parent secrets and pass only explicit whitelist variables (`PATH`, `TEMP`, `SYSTEMROOT`) and process tokens.
- **Sidecar Isolation**: Never import ExLlamaV3 directly in Core. Keep TabbyAPI in its isolated `.venv` (`runtime/tabbyAPI/.venv`).

## 3. Security & Capability Tokens
- **Native OS Modals**: Approvals for high-risk tools must use native Win32 system modal dialogs (`MB_SYSTEMMODAL`, `MB_DEFBUTTON2`). Web UI cannot bypass or auto-approve.
- **One-Shot Capability Tokens**: Tokens issued upon native OS approvals are strictly single-use, bounded by HMAC-SHA256, and bound to deterministic JSON-serialized arguments (`sort_keys=True`, no extra whitespace).
