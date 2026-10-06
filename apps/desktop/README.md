# Project Friday Desktop (Tauri 2 + React 19)

This directory hosts the Tauri 2 / Rust supervisor and React presentation shell.
- `src-tauri/`: Rust process supervisor (Windows Job Object), reverse proxy, and native OS approval dialogs.
- `src/`: React 19 / TypeScript presentation UI communicating purely via Tauri IPC.
