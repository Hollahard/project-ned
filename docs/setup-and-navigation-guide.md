# Project Friday: Setup, Launch & Navigation Guide

This guide provides step-by-step instructions for launching, configuring, and navigating **Project Friday (Project Ned)** on Windows 11 with the NVIDIA GeForce RTX 5090 Blackwell GPU.

---

## 1. System Requirements & Prerequisites

### Hardware
* **GPU**: NVIDIA GeForce RTX 5090 (32 GB GDDR7, Blackwell `sm_120`) or compatible NVIDIA GPU with >= 16 GB VRAM.
* **CPU / RAM**: 8+ Core x86_64 CPU, 32+ GB System RAM.
* **Storage**: Fast NVMe SSD formatted as NTFS (recommended on dedicated drive, e.g. `G:\`).
* **Operating System**: Windows 11 64-bit (Build 22621+ recommended).

### Software Dependencies
* **NVIDIA Display Driver**: Studio or Game Ready Driver **572.16+** (CUDA 12.8 ready).
* **Python Runtime**: Python **3.12** (managed via `uv` or standard venv).
* **Node.js**: Node.js **20 LTS** or newer (with `npm`).
* **Rust**: Rust **1.80+** with the MSVC toolchain (`x86_64-pc-windows-msvc`).
* **Visual Studio Build Tools**: C++ build tools installed for Windows native compilation.

---

## 2. Initial Setup & Installation

### Step 1: Clone Repository & Virtual Environment
Open PowerShell in administrative or standard terminal:
```powershell
# Navigate to your target workspace root
cd G:\Project_Ned

# Initialize Python 3.12 virtual environment using uv
uv venv .venv --python 3.12

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install Friday Core in editable mode
uv pip install -e services/core
```

### Step 2: Install Desktop Frontend Dependencies
```powershell
cd G:\Project_Ned\apps\desktop
npm install
```

### Step 3: Configure Local Environment & Secrets
Project Friday operates strictly offline and sovereign by default. If enabling optional Langfuse observability mirroring, create a `.env` file in the project root:
```env
# Optional Langfuse Observability (Offline by default if omitted)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## 3. How to Launch Project Friday

You can launch Project Friday in either **Desktop GUI Mode** (recommended) or **Headless Service Mode**:

### Option A: Desktop Application Mode (Tauri 2 + React 19)
This is the standard mode for desktop users. It launches the Rust supervisor, cages the Python Core service inside a Windows Job Object, and opens the native GUI window.

```powershell
cd G:\Project_Ned\apps\desktop
npm run tauri dev
```
*Tip: To build a standalone Windows installer (`.exe` or `.msi`), run `npm run tauri build`.*

### Option B: Headless Python Core Service Mode
If you want to run Friday purely as an API daemon or test headless WebSocket workflows:
```powershell
cd G:\Project_Ned
.\.venv\Scripts\Activate.ps1

# Start the Core FastAPI server on loopback
python -m uvicorn friday.api.app:create_app --factory --host 127.0.0.1 --port 8200
```
The Core API will be accessible strictly at `http://127.0.0.1:8200`.

---

## 4. The First-Launch Onboarding Wizard

On your first launch, Project Friday detects that configuration is needed and automatically presents the **5-Step First-Launch Wizard**:

```text
┌─────────────────────────────────────────────────────────────┐
│               PROJECT FRIDAY FIRST-LAUNCH WIZARD            │
│  [1. Welcome] ── [2. Diagnostics] ── [3. Workspace] ── ...  │
└─────────────────────────────────────────────────────────────┘
```

1. **Step 1: Welcome & Sovereign Local Principles**:
   * Outlines local-first privacy, local inference execution, and zero cloud dependency.
2. **Step 2: Hardware & Environmental Diagnostics**:
   * Click **Run Hardware Diagnostics** to verify:
     * **RTX 5090 Blackwell Detection**: Verifies 32 GB GDDR7 VRAM, Blackwell architecture, and CUDA readiness.
     * **Windows Job Object Support**: Confirms kernel process containment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
     * **NTFS Path Boundaries**: Validates filesystem security and absence of dangerous Alternate Data Streams.
3. **Step 3: Workspace Directory Configuration**:
   * Enter your workspace root (e.g. `G:\Project_Ned`).
   * Friday automatically scaffolds `.agents/skills`, `.agents/memory`, `storage`, `config`, and `logs`.
4. **Step 4: Model Profile & Sidecar Configuration**:
   * **Select Model**: Choose your local EXL3 model (e.g. `Mistral-Small-3.1-24B-Instruct-2503-exl3` or `Qwen3-Coder-30B-A3B`).
   * **KV-Cache Quantization**: Select `q6` (recommended for balanced memory/speed), `q8`, or `fp16`.
   * **Context Length**: Set context window (default: `32768` tokens, up to `65536`).
   * **Enable Gaming Mode**: Checked by default.
5. **Step 5: Confirmation & Sovereign Launch**:
   * Review all configuration entries, click **Initialize Sovereign Workspace**, and enter Friday's main interface.

---

## 5. Desktop Interface Navigation

Project Friday’s interface is divided into three primary functional areas:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ [Model Badge] [GPU VRAM: 18.5/32GB] [🎮 GAMING MODE] [⚙️ Setup] [● Ready]│ Header Bar
├──────────────┬─────────────────────────────────────────────────────────┤
│ SESSIONS     │ CHAT & AGENT TIMELINE                                   │
│              │                                                         │
│ [+ New]      │ User: Run security review on services/core.             │
│              │                                                         │
│ Session 1    │ 🤖 Friday:                                              │
│ Session 2    │ ▼ Reasoning (Expanded)                                  │
│              │   Analyzing tools and AST filters...                    │
│              │                                                         │
│              │ Here is the verified analysis...                        │
│              ├─────────────────────────────────────────────────────────┤
│              │ [Type your message...]                [Tokens: 1,420/32K]│ Input Deck
└──────────────┴─────────────────────────────────────────────────────────┘
```

### 1. Header Bar Controls & Live Telemetry
* **Model Name Badge**: Displays the active resident EXL3 model.
* **GPU Telemetry Pill**: Displays live NVIDIA NVML metrics:
  * Current VRAM utilization (e.g. `18.5 GB / 32.0 GB`).
  * Real-time GPU core temperature (e.g. `34°C`).
* **Gaming Mode Button (`GAMING MODE`)**:
  * **What it does**: Instantly aborts any active agent turn and completely unloads the model from VRAM in **under 2 seconds**, releasing over 28 GB of VRAM for AAA gaming.
  * **Button State**: Glows pink when active (`GAMING MODE ACTIVE`). Click again to reload the model profile back into VRAM.
* **Setup & Diagnostics Button (`⚙️ Setup & Diagnostics`)**:
  * Re-opens the hardware diagnostics wizard at any time to re-test the GPU or reconfigure paths.
* **Supervisor Status Indicator**:
  * Green circle indicates the Tauri supervisor process guardian is connected and healthy.

### 2. Left Sidebar (Session Management)
* **`+ New` Button**: Creates a new isolated conversational thread.
* **Session List**: Click any session item to switch context. The active session is highlighted in blue.
* **Persistence**: All messages, tool calls, and event streams are saved automatically in `state.db` using SQLite WAL mode.

### 3. Main Chat Timeline
* **Markdown & Syntax Highlighting**: Code snippets, tables, diffs, and alerts render with syntax highlighting.
* **Reasoning / Chain-of-Thought Accordion**:
  * Click to expand the reasoning drawer to inspect the model's internal thinking trace before tool calls are dispatched.
* **Turn Cancellation (`Cancel Turn`)**:
  * While the assistant is generating or executing tools, a red **Cancel** button appears. Clicking it safely stops inference immediately without corrupting database state.

### 4. Input Deck & Context Budget Indicator
* **Textarea Prompt Box**:
  * Type your prompt and press `Enter` to submit.
  * Use `Shift + Enter` to insert a newline.
* **Context Budget Gauge**:
  * Displays real-time token count against your model's maximum context length (e.g. `1,420 / 32,768 tokens`).
  * As the conversation grows, Friday's dynamic compaction automatically summarizes older turns while tagging them as inert historical context.

---

## 6. Security & Native Approval Prompts

Project Friday enforces a **Zero-Trust** model for tool execution:

* **Low-Risk Tools (Tier 0 & 1)**: Operations like `filesystem.read`, `git.status`, and system information execute automatically within safe workspace roots.
* **High-Risk Tools (Tier 2 & 3)**: Operations such as `terminal.exec` (PowerShell command execution) or writing files outside approved folders trigger a **Win32 Native System Modal Dialog**:

```text
┌──────────────────────────────────────────────┐
│  ⚠️ Project Friday — Security Authorization   │
│                                              │
│  The agent is requesting permission to run:  │
│  Tool: terminal.exec                         │
│  Command: dir G:\Project_Ned                 │
│                                              │
│  [ Approve (Yes) ]     [ Deny (No) ]         │
└──────────────────────────────────────────────┘
```

* **Important Invariant**: The Web UI cannot auto-approve or bypass this dialog.
* Clicking **Approve** issues a one-shot HMAC-SHA256 capability token valid for **120 seconds**, bound exclusively to the exact command arguments.

---

## 7. Troubleshooting & Diagnostics

### Problem: VRAM isn't released after gaming
* **Solution**: Click **Gaming Mode** in the header. If needed, restart the desktop app; the Windows Job Object guarantees all child processes terminate when Friday closes.

### Problem: GPU not detected in Diagnostics
* **Solution**: Ensure NVIDIA Driver **572.16+** is installed and that `nvidia-smi` is accessible in your PowerShell PATH.

### Problem: Database locked errors
* **Solution**: Project Friday uses SQLite in WAL mode. Ensure no third-party SQLite viewer holds an exclusive lock on `state.db`. Run `.\.venv\Scripts\pytest.exe -m soak` to verify WAL health.

---

*For technical architecture details, refer to [`docs/architecture/`](file:///G:/Project_Ned/docs/architecture/) and [`docs/adr/`](file:///G:/Project_Ned/docs/adr/).*
