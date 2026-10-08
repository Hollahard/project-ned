# Bounded backend-host proof

This package proves a Windows owned-process and readiness boundary using a
harmless, standard-library fixture. **Installed Hermes was not launched.**
Fixture HTTP response data is synthetic and is not evidence of retained Hermes
route, Chat, Settings, History or WebSocket parity.

`OwnedProcess` uses `CreateProcessW` with `STARTUPINFOEXW`, an explicit inherited
`HANDLE_LIST` for stdin/stdout/stderr, and an atomic `JOB_LIST`. The unnamed job
has `KILL_ON_JOB_CLOSE`; its handle is not inherited. There is no shell, PATH
lookup, ambient environment merge, PID discovery or port-based termination.
Separate pipe readers drain stdout and stderr concurrently. Raw child logs are
not retained or persisted; only byte counts, bounded readiness parsing and
stable error descriptions are exposed. Use the object as a context manager.

The parser requires complete stdout lines matching the pinned upstream's
`HERMES_BACKEND_READY port=N` or legacy `HERMES_DASHBOARD_READY port=N`. It accepts
the upstream pair when both announce the same valid port, rejects malformed or
conflicting announcements, and bounds line length, total startup output and
time. Readiness is only a port announcement: the caller must still perform
authenticated application readiness and identity checks.

Windows virtual-environment executables can be redirectors: the HTTP-serving
Python PID may differ from the root created PID. `contains_observed_pid` opens
only a query-limited handle to verify current membership in this existing job.
It does not adopt a process or authorize termination by PID. All cleanup uses
the original owned job and process handles. The fixture test verifies the
authenticated server's observed PID belongs to the job.

Cleanup terminates the owned job, checks active processes reach zero, waits on
the original process handle, and waits for pipe EOF. Verification failures are
reported even though handles are still closed. This spike supplies bounded
forced cleanup; production cooperative shutdown and durable resource policy
remain separate work. No VRAM-release claim follows from these tests.

## Verification

Run in this package directory after activation. Native tests may require scoped
sandbox elevation on this Windows machine; they launch only this package's
fixture, using the existing Project_Ned interpreter and fresh test directories.

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
python -m pytest -q --basetemp=.pytest-tmp *> backend-host-test-results.txt
python -m ruff check src tests
python -m ruff format --check src tests
```

The tests cover fragmented/dual/truncated/malformed readiness, bounded output,
literal Unicode arguments, real loopback port-zero HTTP, missing/wrong-token
rejection, query-only job membership, absence of ambient tokens/PATH, an
unlisted inheritable handle, stderr flooding, early exit/timeouts, descendants,
independent-job survival, partial native-constructor failures, and failure to
verify cleanup. Credentials are generated in memory and supplied only through
the fixture's explicit environment; they never enter argv, files or reports.

## Why stock Hermes was not launched

The inspected checkout is commit `649d6c0391029f35959cfbc240eb3534a6667cf5`.
`source-audit.json` records selected source hashes, not a full import-closure or
runtime attestation. The relevant code was inspected read-only:

- `hermes_cli/web_server.py:1465` calls `_publish_host_rendezvous` even for
  `--isolated`. That function has no isolation bypass and can claim/reclaim the
  host lock. `gateway/host_rendezvous.py:498–502` persists the generated session
  credential to `host-serve.token`. A fresh home cannot satisfy a requirement
  forbidding credential persistence through this stock path.
- `web_server.py:1410` invokes orphan-MCP cleanup regardless of the desktop-owned
  flag. Avoiding `HERMES_DESKTOP` prevents a separate desktop reaper but does not
  prevent this sweep. `--isolated` is discovery opt-out, not complete isolation.
- `hermes_bootstrap.py:588–613` prepares launch, recovery and dependencies before
  normal command dispatch. `HERMES_DISABLE_LAZY_INSTALLS=1` guards one repair
  path, not a proven absence of all runtime-store/lease changes.
- `web_server.py:283–304` starts local-runtime and free-tier background bootstrap
  in lifespan. Hosted-room recovery, other background startup and deferred MCP
  discovery must also be accounted for.
- `tui_gateway/server.py:55–56` loads project dotenv data at import, and its import
  path starts an idle session reaper at line 421. A fresh `HERMES_HOME` alone
  does not isolate source dotenv, machine state, user-profile or cache paths.

These blockers are source findings, not observed changes from an actual launch.
No installed interpreter environment, source file, user config or service changed.

## Proposed next managed diagnostic mode

This is a reviewable proposal, **not an implemented or cleared launch path**:

1. Build a new hash-guarded managed package, keeping the installed checkout
   read-only. Enter through an explicit diagnostic module, never
   `hermes_cli.main`, `hermes_bootstrap`, `tui_gateway.entry`, stock `start_server`
   or stock `_on_server_started`.
2. Preserve audited Hermes route functions but replace startup orchestration
   explicitly: minimal required ASGI state and owned SessionDB lifespan, own
   Uvicorn socket/port-zero handling and readiness emission. Name the disabled
   facilities in the manifest: rendezvous/attachment, global reaping, update and
   dependency repair, hosted-room recovery, cron, metrics, plugins, free-tier
   bootstrap, local-runtime boot, parent/watchdog registry and MCP discovery.
   This is a diagnostic subset, not stock startup parity or a production host.
3. Hash-guard copied source seams before removing installer fallback
   (`web_server.py:44–49`), plugin mounting (line 1066), project dotenv loading
   (`tui_gateway/server.py:56`), import-time reaper startup (line 421) and deferred
   MCP-on-WebSocket startup (`hermes_cli/web_routers/chat_ws.py:705–710`). Audit
   the remaining transitive imports before execution; direct web-server import
   alone is insufficient.
4. Require an explicit fresh home/cache/temp/machine-state root and sanitized
   environment. Disable bytecode and user-site writes. Inject the ephemeral
   session credential through the owned environment only; remove it after
   consumption. Disable access/content logging. No fallback to user config or
   source dotenv. Verify the installed tree remains unchanged.
5. Enforce a diagnostic request allowlist **before** upstream dispatch. First
   admit only the audited read-only config/session-list/health slices. Reject
   model execution, session creation, prompts, tools, PTY and all mutations.
   Add a WebSocket `ping` proof only after auditing its handshake/import path.
6. Verify real source handler shapes, authentication failures, owned identity,
   bounded readiness/errors, filesystem write scope and job cleanup. Keep
   fixture and retained-handler evidence separately labeled. Only then expand
   toward full Chat/Settings/History behavior.

The proof-local ctypes launcher duplicates a narrow part of the tested Rust
resource-host boundary. Consolidate captured pipes and explicit inheritance
into that host before production integration; do not ship competing process
owners. Durable coordinator admission, profile routing and Tauri registration
remain with the architecture's existing owners.

Windows mechanisms: [process attribute lists](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
and [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).
