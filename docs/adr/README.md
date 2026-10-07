# Architecture Decision Records (ADRs)

This directory contains the Architecture Decision Records for **Project Friday (Project Ned)**.

## Index

| ADR | Title | Status | Date | Decision Summary |
| :--- | :--- | :--- | :--- | :--- |
| [**0001**](0001-pinned-inference-runtime.md) | Pinned Inference Runtime for NVIDIA RTX 5090 | **Accepted** | 2026-10-06 | Pinned TabbyAPI (`2fd6cc76`), ExLlamaV3 (`1.5.4+cu132`), PyTorch (`2.11.0+cu130`), and Triton Windows for Blackwell `sm_120`. |
| [**0002**](0002-continuous-soak-and-endurance-testing.md) | Continuous Soak and Long-Run Endurance Testing Architecture | **Accepted** | 2026-10-07 | Defined tripwire memory slope (<50 MB/h), VRAM recovery within 512 MB, SQLite WAL bounds (<64 MB), and scripted fault harness. |

---

## Architectural Invariants Matrix

Every technical decision in Project Friday is governed by five non-negotiable architectural invariants:

1. **Host-Side Supervised Containment**: All worker processes, inference sidecars, and subagents must reside inside the Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and breakaway strictly prohibited.
2. **Zero-Trust Loopback Security**: The Tauri 2 supervisor acts as the reverse proxy. WebViews never hold API keys or admin tokens. High-risk actions require native Win32 system modal dialogs and HMAC-SHA256 one-shot capability tokens.
3. **Monotonic Capability Scoping**: Delegated subagents and scheduled background tasks are strictly bounded. Subagents are depth-1 only; authority is monotonic; recursive delegation (`subagent.*`, `schedule.*`, `policy.*`) is unconditionally rejected.
4. **Hardware Affinity (RTX 5090 Blackwell)**: The single resident model policy is enforced. Gaming Mode releases VRAM via cancellation and unloading rather than process swapping.
5. **Durable Local Sovereignty**: SQLite WAL mode with immediate busy timeouts, local sovereign JSONL telemetry, and zero unhandled exceptions.

---

## ADR Lifecycle

```text
Proposed ──> Accepted ──> Deprecated ──> Superseded
                 │
                 └──> Rejected
```

1. **Proposed**: Under team discussion or draft review.
2. **Accepted**: Formally approved and verified in the codebase.
3. **Deprecated**: Superseded or no longer applicable.
4. **Superseded**: Replaced by a subsequent ADR.

## Creating a New ADR

1. Copy the MADR format: `NNNN-title-with-dashes.md`.
2. Follow the required sections: *Status, Context, Decision Drivers, Considered Options, Decision, Consequences, Compliance Verification*.
3. Add an entry to the index above and link relevant commits.
