# Project Friday (Project Ned)

> A sovereign, single-user Windows desktop AI agent harness optimized for the NVIDIA RTX 5090 (32 GB GDDR7), powered by TabbyAPI and ExLlamaV3 with Hermes-parity agent capabilities and strict zero-trust boundaries.

---

## Architecture Overview

Friday is split into three strictly separated domains:

1. **Desktop Shell (`apps/desktop`)**:
   - Built with **Tauri 2 / Rust + React / TypeScript**.
   - The UI acts purely as presentation over Tauri IPC.
   - The Rust backend owns process supervision (Windows Job Objects), credential holding, and native OS approval dialogs.
   - The WebView **never** speaks HTTP to Core or TabbyAPI.

2. **Friday Core (`services/core`)**:
   - Python packages with FastAPI transport, bound strictly to `127.0.0.1`.
   - Houses the multi-step agent loop, tool execution policy engine, session store (SQLite WAL), memory manager, and scheduler.
   - Communicates with TabbyAPI via OpenAI-compatible endpoints.

3. **Inference Sidecar (TabbyAPI + ExLlamaV3)**:
   - Friday directly owns and supervises the TabbyAPI process on `127.0.0.1`.
   - Native EXL3 format inference utilizing the full 32 GB VRAM on RTX 5090.
   - Quitting Friday or activating Gaming Mode terminates TabbyAPI and completely releases VRAM.

---

## Directory Structure

```text
Project_Ned/
├── apps/
│   └── desktop/                 # Tauri 2 (Rust) + React 19 (TypeScript) UI
├── services/
│   └── core/                    # Friday Core Python service & agent engine
├── contracts/                   # JSON Schema specifications for events, API, and tools
├── config/                      # Configuration and model profile templates
├── tests/
│   ├── integration/             # Component integration tests
│   ├── security/                # Policy, path canonicalization & red-team tests
│   └── e2e/                     # End-to-end lifecycle verification
└── docs/
    ├── architecture/            # Architecture specifications & design invariants
    └── adr/                     # Architecture Decision Records
```

---

## Quickstart

### Documentation & Operational Guides
- 📖 [**Setup & Navigation Guide**](docs/setup-and-navigation-guide.md): Comprehensive instructions on prerequisites, environment verification, launching desktop/headless modes, the 5-step setup wizard, and UI navigation.
- 🚀 [**Release Notes (v1.0.0)**](RELEASE_NOTES.md): Architecture highlights, hardware qualification on RTX 5090, Production Readiness Review, and release invariants.
- 📋 [**Changelog**](CHANGELOG.md): Detailed phase-by-phase history covering all 16 completion phases.
- 🏛️ [**Architecture Decision Records (ADRs)**](docs/adr/README.md): Index of technical decisions (pinned inference runtime, continuous soak testing, etc.).

### Prerequisites
- Windows 11 64-bit
- NVIDIA RTX 5090 (or CUDA-capable GPU, Driver 572.16+)
- Python 3.12+ (managed with `uv`)
- Node.js 20+
- Rust 1.80+ with MSVC toolchain (for Tauri 2 desktop shell)

### Launching Friday
See the [**Setup & Navigation Guide**](docs/setup-and-navigation-guide.md) for full instructions:
- **Desktop Application (Tauri 2 GUI)**:
  ```powershell
  cd apps/desktop
  npm install
  npm run tauri dev
  ```
- **Headless Core API**:
  ```powershell
  .\.venv\Scripts\python.exe -m uvicorn friday.api.app:create_app --factory --host 127.0.0.1 --port 8000
  ```

