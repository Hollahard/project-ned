# Project Friday — Release Notes v1.0.0

**Release Tag**: `v1.0.0`  
**Date**: October 7, 2026  
**Target Platform**: Windows 11 x64  
**Hardware Accelerator**: NVIDIA GeForce RTX 5090 (32 GB GDDR7, Blackwell `sm_120`)  
**Repository**: [https://github.com/Hollahard/project-ned](https://github.com/Hollahard/project-ned)

---

## 1. Executive Summary

Project Friday v1.0.0 is a sovereign, local-first artificial intelligence desktop agent harness engineered specifically for high-performance Windows workstations powered by the NVIDIA GeForce RTX 5090 Blackwell GPU.

Unlike cloud-dependent agent platforms, Project Friday guarantees total operational sovereignty: all model weights, conversation histories, episodic memories, and scheduled automations execute locally. High-risk actions are guarded by native Win32 system modal dialogs and kernel-level Windows Job Objects, ensuring that agent capabilities remain strictly bounded and auditable.

---

## 2. Architecture & Core Subsystems

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Tauri 2 Rust Supervisor                         │
│  - Reverse Proxy (127.0.0.1)     - Windows Job Object Process Guardian │
│  - Native Win32 Modal Approvals  - Cryptographic Capability Tokens     │
└───────────────┬────────────────────────────────────────┬───────────────┘
                │ IPC Proxy (Loopback Only)              │ Process Cage
┌───────────────▼────────────────┐      ┌────────────────▼───────────────┐
│       React 19 Desktop UI      │      │       Python Core Service      │
│ - Chat Timeline & Context Gauges│      │ - Multi-Step Agent Reasoning   │
│ - Hardware Telemetry & Gaming  │      │ - SQLite WAL + FTS5 Memory     │
│ - First-Launch Setup Wizard    │      │ - Task Scheduler & Subagents   │
└────────────────────────────────┘      └────────────────┬───────────────┘
                                                         │ HTTP / IPC
                                        ┌────────────────▼───────────────┐
                                        │   TabbyAPI + ExLlamaV3 Sidecar │
                                        │ - RTX 5090 Blackwell (sm_120)  │
                                        │ - 24B–30B EXL3 Quantized LLM   │
                                        │ - Isolated Python 3.12 Runtime │
                                        └────────────────────────────────┘
```

### Core Components
1. **Desktop Supervisor (`apps/desktop/src-tauri`)**:
   - Manages child process lifecycles via Windows Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
   - Acts as a reverse proxy shielding Core Bearer tokens and Tabby admin keys from WebViews.
   - Issues single-use HMAC-SHA256 capability tokens upon native Win32 modal approval.
2. **Core Agent Runtime (`services/core/src/friday`)**:
   - Multi-step tool use, reasoning loops, and prompt compaction.
   - 4-tier persistent memory (Episodic, Semantic, Working, Procedural) with SQLite WAL and FTS5 full-text search.
   - Autonomous task scheduler with frozen permission snapshots and atomic lease claiming.
   - Depth-1 monotonic subagent delegation with strict anti-recursion barriers.
3. **Local Inference Sidecar (`runtime/tabbyAPI`)**:
   - High-throughput ExLlamaV3 execution on RTX 5090 Blackwell (`sm_120`).
   - Qualified on 24B–30B models (Mistral Small, Qwen 2.5/3.5 Coder) delivering ~94.5 tokens/sec.
   - One-click Gaming Mode for instant turn abort and full VRAM release.

---

## 3. Hardware Qualification Profile

* **GPU**: NVIDIA GeForce RTX 5090 (32 GB GDDR7, Blackwell `sm_120`, Compute Capability `12.0`)
* **Host Driver**: NVIDIA Studio / Game Ready Driver 572.16+
* **CUDA / PyTorch**: CUDA 12.8, PyTorch 2.11.0+cu130, ExLlamaV3 1.5.4+cu132
* **Inference Stress Test**: 20 consecutive load/unload cycles surviving with 0 memory leaks (ADR-0001).
* **Soak Endurance**: Private Bytes drift < 50 MB/h, WAL size < 64 MB, post-unload VRAM returning within 512 MB of baseline (ADR-0002).

---

## 4. Production Readiness Review (PRR) Audit Matrix

| Verification Vector | Requirement | Observed Status | Verdict |
| :--- | :--- | :--- | :--- |
| **Process Cage** | Child processes bound to Job Object with zero breakaway | All workers, sidecars, and subagents caged | **PASS** |
| **ActiveProcessLimit** | Supervisor job does NOT set `ActiveProcessLimit = 1` | `ActiveProcessLimit` strictly avoided | **PASS** |
| **Path Traversal Defense** | Rejection of junction attacks, ADS (`:`), and device names | `GetFinalPathNameByHandleW` verified | **PASS** |
| **Script Sandboxing** | PowerShell restricted language mode; AST violation rejection | Reflection, scriptblocks, pipelines blocked | **PASS** |
| **Delegation Boundaries**| Subagent depth limit strictly enforced at depth 1 | Recursive grandchildren unconditionally denied | **PASS** |
| **Scheduler Containment**| Unattended jobs run network-off with frozen permission snapshot | Restricted tool calls fail closed | **PASS** |
| **Memory Leak Soak** | Continuous soak harness verifies bounded memory slope | 191 Python tests pass; soak endurance green | **PASS** |
| **Desktop Tests** | Zero handle leaks in supervisor during repeated diagnostics | `cargo test` passes 13/13; handle diff <= 15 | **PASS** |
| **UI Contracts** | Frontend passes contract schemas and bundling | `npm test` passes 13/13; Vite build clean | **PASS** |

---

## 5. Operational Boundaries & Known Limitations

1. **Secrets at Rest (`.env` vs DPAPI)**:
   - *Current State*: Langfuse and local credentials reside in `G:\Project_Ned\.env` (gitignored and local).
   - *Roadmap*: Windows DPAPI / Credential Manager integration is scheduled for v1.1 hardening.
2. **Interactive Host APM Faults**:
   - Host sleep/resume (`host_sleep_resume`) and workstation lock/unlock (`host_lock_unlock`) fault injections require an interactive user desktop session and are marked `SKIPPED` in headless automated test runs.
3. **Single Resident Model Policy**:
   - Gaming Mode operates via cancellation, unloading, and VRAM release rather than concurrent model swapping. Dual-model residency is unsupported on a single GPU.

---

## 6. Test Coverage Summary

| Suite | Tests | Duration | Result |
| :--- | :---: | :---: | :---: |
| `services/core/tests/` (core, telemetry, sessions, memory, scheduler) | 180+ | — | ✅ All pass |
| `tests/security/` (12 red-team attack vectors) | 12+ | — | ✅ All pass |
| `tests/e2e/` (end-to-end agent turns) | — | — | ✅ All pass |
| `tests/soak/test_soak_endurance.py` (`@pytest.mark.soak`) | 5 | 4.1 s | ✅ All pass |
| `apps/desktop/src-tauri` Rust supervisor endurance | 15 | 0.89 s | ✅ All pass |
| **Total** | **216+** | **21.1 s** | ✅ **Zero failures** |

Soak endurance (smoke mode): **422 agent turns** — Private Bytes slope green, VRAM delta 0.0 MB, 0% error rate.

---

## 7. Security Advisories

**SA-001 — WebView Trust Boundary**  
The React WebView holds no credentials and cannot spawn processes or call Core/TabbyAPI directly. All communication is Tauri IPC through the Rust proxy. Do not modify `tauri.conf.json` capabilities to expose the shell plugin to the WebView.

**SA-002 — Skill Auto-Loading**  
Skills loaded from a workspace are data — they are never auto-executed. Do not enable auto-loading of `SKILL.md` files from untrusted repositories. Skill writes require native dialog approval and a diff review.

**SA-003 — Credentials at Rest**  
Langfuse credentials are loaded from `.env` (gitignored). Ensure this file has restrictive NTFS ACLs (owner read-only). Migration to Windows DPAPI / Credential Manager is planned for v1.1.

---

## 8. Verification & Quickstart Runbook

### Full Multi-Stack Verification
```powershell
# 1. Run Python Core, Security & Soak Test Suites
.\.venv\Scripts\pytest.exe -v

# 2. Run Rust Supervisor Integration Tests
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml

# 3. Run Desktop Frontend Contract Tests
npm --prefix apps/desktop test

# 4. Run Fast Soak Endurance Suite (<3 min)
.\.venv\Scripts\pytest.exe -m soak tests/soak/test_soak_endurance.py -v
```

### Launching the Desktop Application
```powershell
# Start Desktop App in Development Mode
npm --prefix apps/desktop run tauri dev
```
On initial launch, the **First-Launch Wizard** will guide you through hardware diagnostics, workspace directory confirmation, and model preset bootstrapping.

---

## 9. Phase Commit Reference

| Phase | Description | Commit |
| :---: | :--- | :--- |
| 1 | TabbyAPI + ExLlamaV3 qualification on RTX 5090 | `8cea925` |
| 2 | Headless WebSocket streaming and cancellation | `9713054` |
| 3 | Tauri 2 supervisor, Job Object, proxy, native approvals | `cd36496` |
| 4 | Chat sessions, context budget manager, React 19 shell | `8e6fbab` |
| 5 | Model manager, NVML telemetry, VRAM preflight, Gaming Mode | `4bebb61` |
| 6 | Agent loop guardrails, NTFS junction defense, native read tools | `985c1d9` |
| 7 | Writes, terminal exec, PowerShell AST defense, verify-on-stop | `7567f8f` |
| 8 | MCP host, Job Object client, tool adapter | `b88acf6` |
| 9 | 4-tier memory, FTS5 scoped joins, injection defense | `b924d0e` |
| 10 | Inert data gating (10A) and sandbox host (10B) | `8a76c16` |
| 11 | SQLite scheduler, frozen permissions, safe recovery | `5eb9688` |
| 12 | Depth-1 subagent delegation, monotonic permissions, anti-recursion | `c7ba4ed` |
| 13 | Structured observability, dual-sink tracing, Langfuse integration | `8e25164` |
| 14 | Security regression suite, 12 red-team attack vectors | `7f7978b` |
| 15 | Tauri installer packaging, bundle config, first-launch wizard | `c74a6c6` |
| 16 | Continuous soak and long-run endurance harness | `cc4967a` |
| **v1.0.0 HEAD** | Cleanup | **`eab3048`** |

---

*Project Friday v1.0.0 — Built on the RTX 5090 Blackwell. The harness is the product.*
