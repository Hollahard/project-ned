# Project Friday — Revised Architecture and Implementation Plan

Status: working plan after architecture review  
Date: 2026-10-05  
Target: single-user Windows desktop agent harness on an RTX 5090 32 GB  
Parity goal: weighted local-desktop harness parity with Hermes Agent, not a line-by-line clone and not an LM Studio clone

This plan supersedes the earlier PostgreSQL-first design and the “move filesystem and terminal into MCP” direction. It keeps the recommended runtime split and applies the security revisions as invariants, not as a later hardening phase.

---

## 1. Judgment

Build a desktop agent operating system whose inference engine happens to be ExLlamaV3.

Friday owns the model server. Launching Friday starts TabbyAPI. Closing Friday terminates TabbyAPI and releases VRAM. There is no separately managed LM Studio process.

The model is interchangeable. The harness is the product: session state, tool policy, memory, skills, approvals, and process ownership.

Feasible scope for v1 is a local agent that can reason, call a small native tool set, remember, use approved MCP plugins, and exploit the 5090 directly. Messaging gateways, computer use, voice, and browser automation are explicitly out of the first release.

Expected local-desktop parity after the capability phases: roughly 90–94% of the Hermes surface that matters on one Windows machine. Security is not part of that percentage. Security is a zero-unauthorized-side-effect bar.

---

## 2. What changed from the previous plan

| Previous direction | Revised direction | Why |
|---|---|---|
| React obtains a bearer and calls FastAPI | Rust proxies every Core and Tabby call | A WebView must not hold credentials |
| Approval is a React modal / WebSocket event | Native dialog owned by Rust, one-shot token | XSS or a local process must not click Approve |
| Filesystem and terminal “increasingly become MCP” | Native tools for core I/O; MCP for external plugins only | MCP stdio is code execution; policy belongs in Friday |
| `python.exec` in the first tool set | Not in v1 | It is a shell |
| Policy engine after the agent loop | Policy engine in the first tool commit | Direct-exec paths are hard to remove later |
| Shell denylist, including “readonly PowerShell” | AST allowlist, Constrained Language Mode, no `shell=True` | Encoded commands and cradles bypass denylists |
| Path prefix checks | Canonical final path after open | Junctions, symlinks, `\\?\`, ADS, device paths |
| Skill files auto-load from a workspace | Skills are data; writes need native approval; never auto-load from a repo | Skill write is stored prompt injection |
| Scheduled job re-reads live policy | Permission snapshot frozen at schedule time | Unattended execution must not gain tools later |
| Silent cloud fallback | Explicit per-turn opt-in | Fallback is an exfiltration path |
| Job Object for cleanup only | Job Object plus breakaway denied, scrubbed child environment | Cleanup is not isolation |
| Vendor Hermes early | Own the inference adapter and session store first; vendor only after review | MIT does not transfer a subprocess policy |
| Role-model swap as the default | One resident model; swaps are a later feature | Load/unload races dominate latency |

---

## 3. Runtime domains

```text
┌──────────────────────────────────────────────────────────────┐
│ FRIDAY DESKTOP                                                │
│ Tauri 2 / Rust + React / TypeScript                           │
│ UI, process supervisor, credential holder, native approvals   │
│ The WebView never speaks HTTP to Core or TabbyAPI            │
└──────────────────────────┬───────────────────────────────────┘
                           │ Tauri IPC only
                           │ Rust holds bearer + Tabby admin key
┌──────────────────────────▼───────────────────────────────────┐
│ FRIDAY CORE                                                   │
│ Python packages + FastAPI transport                           │
│ Agent loop, tools, policy, memory, jobs                       │
│ Bind 127.0.0.1 only. Reject non-loopback Host / Origin.       │
└────────────┬──────────────────────────────┬──────────────────┘
             │ OpenAI-compatible            │ SQLite
             │ via InferenceBackend         │ WAL + FTS5
┌────────────▼──────────────┐    ┌──────────▼──────────────────┐
│ TabbyAPI sidecar          │    │ state.db                     │
│ ExLlamaV3 / EXL3          │    │ sessions, memory, jobs,      │
│ 127.0.0.1, auth on        │    │ audit; secrets via DPAPI     │
│ admin key in Rust only    │    └──────────────────────────────┘
└────────────┬──────────────┘
             │
      RTX 5090 32 GB GDDR7
```

Four rules keep the domains honest:

1. FastAPI is an interface, not the agent. The loop, registry, memory, scheduler, and policy are importable Python packages tested without Uvicorn.
2. React is presentation. It cannot spawn processes, read arbitrary files, or hold a model-admin credential.
3. TabbyAPI is an application-owned sidecar, pinned to a qualified commit. Friday does not import ExLlamaV3 in the agent process.
4. MCP is an extension host. It is not the implementation of filesystem, terminal, git, or memory.

---

## 4. Security invariants

These are exit criteria for every phase that introduces a side effect. They are not deferred to a security sprint.

### Trust boundary
- Desktop traffic is Tauri IPC. Rust is the only HTTP/WebSocket client of Core and TabbyAPI.
- Core and TabbyAPI bind `127.0.0.1` only, not `0.0.0.0`. Also bind or explicitly refuse `::1` so IPv6 is not an accidental listener.
- Per-launch bearer for Core. Separate Tabby admin key. Neither appears in the WebView, query strings, logs, or crash dumps.
- CORS is disabled, or allows only the Tauri origin. Validate `Host` and `Origin` on HTTP and WebSocket.
- Tauri capability set is narrow. The shell plugin is not exposed to the WebView. No remote page in the webview; asset protocol only. Updater requires signature verification.

### Approvals
- The model proposes a tool call. It never executes one.
- Rust shows a native OS dialog. A React modal cannot grant permission.
- Yes mints a one-shot capability token bound to the exact tool name and canonical arguments.
- No “always allow” for shell, PowerShell, registry write, process kill, or MCP. Later session grants, if any, are hash-scoped, expiring, and never cover those classes.
- Parallel calls are authorized individually. One approval does not cover a sibling.

### Process and filesystem
- Spawn with an argument vector. Never `shell=True`. Never `cmd.exe /c` for MCP or tools.
- PowerShell runs in Constrained Language Mode. Parse the AST. Allow an explicit cmdlet set. Refuse `-EncodedCommand`, `-ExecutionPolicy Bypass`, and nested shells.
- Safe roots are checked on the final path after open (`GetFinalPathNameByHandle`), not by string prefix. Junctions, symlinks, 8.3 names, UNC, device paths, and alternate data streams fail closed.
- Before the first write in a turn: git checkpoint if the target is a repo, file snapshot otherwise.
- Child processes go into the Friday Job Object. `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is on. Breakaway is denied.
- Child environment is an explicit map: `PATH`, `TEMP`, a private app-data directory, and only the credential that process needs. No `os.environ` copy.
- Job Object cleanup is not a sandbox. Low integrity or AppContainer is a later containment step, not a v1 claim.

### Untrusted content
- Web pages, files, tool results, MCP output, retrieved memory, skill text, and compression summaries are data. They are injected in a user or tool role, never in the system prompt.
- A summarizer must not be able to promote “the user approved this” into a rule.
- Workspace `SKILL.md` is never auto-loaded. Skill create/update requires the native dialog and a diff. A skill cannot grant tools or roots the creating session did not already have.
- Memory writes that change approval posture, credentials, or paths require approval. Do not persist every sentence.

### Unattended work and delegation
- A scheduled job freezes its profile, tool allowlist, roots, and network flag at creation. Restart does not re-interpret it under a broader policy. A tool-set change invalidates the job until the user re-saves it.
- Default for jobs: network off, terminal read-only, no fail-open on a missing approval.
- A subagent receives a strict subset of the parent’s tools and roots. It cannot spawn subagents. Its summary is untrusted input to the parent.
- Cloud inference fallback is opt-in per turn. Never silent failover on OOM.

### Supply chain and secrets
- Pin TabbyAPI and ExLlamaV3 to the commits that passed the inference gate. Verify checksums. Prefer signatures. Do not track `main`.
- Do not `uvx` or `npx` an MCP server on first use without a lockfile.
- Do not execute Python from a model repository. Treat Jinja chat-template overrides as code.
- Secrets at rest use Windows DPAPI or Credential Manager, not plaintext SQLite.
- `sqlite-vec` loads only from a known extension path. Arbitrary `load_extension` is off.
- Prompt logging is opt-in. Redact secrets in logs and tool output.

---

## 5. Repository Layout

```text
project-friday/
├── apps/
│   └── desktop/
│       ├── src/                         # React / TypeScript, presentation only
│       └── src-tauri/
│           ├── capabilities/
│           └── src/
│               ├── runtime.rs           # lifecycle, readiness
│               ├── processes.rs         # Job Object, spawn, kill
│               ├── proxy.rs             # the only Core/Tabby client
│               ├── approvals.rs         # native dialogs, one-shot tokens
│               └── commands.rs          # narrow IPC
├── services/
│   └── core/
│       ├── pyproject.toml
│       └── src/friday/
│           ├── api/                     # FastAPI adapters
│           ├── agent/                   # loop, turn, cancellation
│           ├── inference/               # InferenceBackend, Tabby adapter
│           ├── tools/                   # registry, policy, native tools
│           ├── mcp/                     # client wrapper, not the wire protocol
│           ├── memory/
│           ├── sessions/
│           ├── scheduler/
│           ├── security/
│           ├── storage/
│           └── telemetry/
├── contracts/
│   ├── events.schema.json
│   ├── api.schema.json
│   └── tool.schema.json
├── config/
│   ├── friday.example.toml
│   └── models.example.toml
├── tests/
│   ├── integration/
│   ├── security/
│   └── e2e/
└── docs/
    ├── architecture/
    └── adr/
```
