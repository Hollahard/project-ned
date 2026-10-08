# Owned Python profile control host

This Rust library launches and owns one CPU-only Python profile worker through private inherited stdio. The application supplies a pinned local launch manifest; renderer requests can use only seven finite profile/status operations. This slice persists named `LoadProfile` settings in the worker's SQLite store. It does not start Hermes, Tabby, a model, an HTTP listener or GPU work.

## Public API

- `ControlHost::from_config(&Path)` verifies the host-selected manifest, launches an owned worker, validates its hello and internally calls `service.describe`.
- `ControlHost::request(&mut self, operation, payload)` runs one correlated request with a bounded deadline. IDs are generated monotonically by the owner and cannot be selected by callers.
- `ControlHost::retire()` and `retire_with_timeout(duration)` stop admission, request cooperative shutdown, and reserve part of the deadline for owned Job termination if needed. Successful retirement reports root exit, both output EOFs and zero Job members. Invalid delayed shutdown output prevents a cooperative-success claim.
- `ControlState::from_optional_config()` reads only the host's `HERMES_NATIVE_CONTROL_CONFIG` variable. Missing configuration keeps the service unavailable.
- `ControlState::try_admit(operation, &payload)` validates a request and atomically reserves the single operation permit. Acquire it **before** scheduling a blocking task, then move it into the task and call `permit.request(operation, payload)`. Dropping a cancelled queued task releases its permit. Synchronous callers can use `ControlState::request`.
- `ControlState::retire(duration)` permanently closes shared admission and bounds mutex acquisition plus cleanup by the supplied deadline. An already running request observes retirement before releasing its guard and completes cleanup. A timeout reports incomplete cleanup instead of claiming success.

The desktop shell's [window owner](../../apps/desktop-shell/src/control.rs) and [async command](../../apps/desktop-shell/src/main.rs) enforce the exact main-window capability, native window identity and local origin before requesting a permit and scheduling `spawn_blocking`. The native command is `hermes_control_request {operation, payload}`. It accepts no executable, manifest, source, environment or state directory input. `service.describe` and `service.shutdown` remain internal owner operations.

The exposed operations are `runtime.status`, `profiles.schema`, `profiles.validate`, `profiles.list`, `profiles.get`, `profiles.save` and `profiles.delete`. Successful result objects are checked against exact shapes before release. Unknown result fields, credential-like extra fields, duplicate JSON keys, wrong IDs and unknown error codes fail the generation. Only finite application errors receive static messages; arbitrary child exception/log text is never returned. Raw stdout/stderr tails are disabled.

## Pinned launch configuration

The manifest schema is exactly version 1 with these fields:

```json
{
  "schema_version": 1,
  "python": {"path": "C:\\trusted\\python.exe", "sha256": "<64 lowercase hex characters>"},
  "bootstrap": {"path": "C:\\trusted\\control-worker\\bootstrap.py", "sha256": "<sha256>"},
  "inference_src": "C:\\trusted\\inference\\src",
  "state_dir": "C:\\owned\\control-state",
  "sources": {
    "worker/__init__.py": "<sha256>",
    "worker/errors.py": "<sha256>",
    "worker/profiles.py": "<sha256>",
    "worker/state.py": "<sha256>",
    "worker/protocol.py": "<sha256>",
    "inference/__init__.py": "<sha256>",
    "inference/admission.py": "<sha256>",
    "inference/errors.py": "<sha256>",
    "inference/profiles.py": "<sha256>"
  },
  "startup_timeout_ms": 10000,
  "request_timeout_ms": 5000,
  "shutdown_timeout_ms": 3000
}
```

The manifest is capped at 64 KiB. The executable is capped at 64 MiB and each pinned source/bootstrap file at 1 MiB. Unknown, duplicate or missing fields fail. All selected paths must be absolute local-drive paths without parent traversal, symlinks or junctions; mapped network drives are rejected. The manifest helper resolves the host-selected input paths first, so the uv base-interpreter alias can be converted into its real versioned location before pinning.

`scripts/prepare_config.py` creates a new state directory and a new manifest without launching anything. It refuses an existing output or state directory. The manifest is outside child state. Example using explicit local choices:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
python scripts/prepare_config.py --python '<absolute base python.exe>' --worker-root '<absolute control-worker package>' --inference-src '<absolute inference/src>' --state-dir '<new absolute state directory>' --output '<new absolute launch.json>'
```

The base Python process uses exactly `-I -S -B -X utf8 bootstrap.py --inference-src ... --state-dir ...`, with its working directory equal to state. Environment construction includes only the Windows directory returned by the Windows API and explicit state paths for temporary/home locations. It does not inherit the launching process's environment, keys, PATH, virtual environment or Python configuration.

The worker's finite source-only loader compiles the pinned public-package `.py` modules directly and excludes bytecode/native-extension shadowing. Existing state may contain only the worker's SQLite database, rollback journal and lock file; the worker additionally verifies file/link/size constraints and holds a process-lifetime exclusive lease. A second writer fails without taking ownership of or stopping the first worker.

These hashes are integrity checks immediately before launch. They do not pin executable/source file mappings against an unrelated concurrent writer, attest every Python DLL/stdlib byte, or provide an operating-system sandbox. Windows filesystem/kernel calls have no hard real-time scheduling guarantee. Packaging and filesystem permissions remain separate production gates.

## Protocol and retirement

The resource owner supplies the exact inherited handle list, suspended creation and Job assignment before resume. Framed input uses bounded nonblocking byte-pipe writes. Output is independently drained into bounded LF/UTF-8 frames. Each frame is at most 65,536 bytes including LF; the output queue holds at most eight complete frames plus one bounded partial frame. No shell, localhost authentication secret or nested Python supervisor is involved.

The first frame must identify `hermes-control-v1`, `hermes-control-worker` and `runtime_attached:false`. The internal describe response must match the complete method set and limits. Calls use at most the worker's 4,096-ID session allowance, with owner operations reserved. There is no automatic restart or request retry.

A malformed response, wrong/duplicate ID, queued unsolicited message, transport timeout, output overflow or crash retires the whole owned generation. An operation may have run before its response is lost; callers must reconcile saved state after explicitly starting a new generation. Ordinary profile validation, missing-profile, capacity and optimistic-revision errors leave a healthy generation usable.

Cleanup success is distinct from application success. The host requires root exit, real EOF on both pipes, finished drainers and zero active Job members. Cooperative success additionally requires a valid acknowledgment and no complete or partial trailing protocol data after EOF. On uncertain cleanup the Job handle is still dropped as final kill-on-close containment, but no cleanup-success report is fabricated. Destructors do not make requests or wait for child cooperation; explicit `retire` is needed for a verified report.

## Verification

Run from this package with the staged or assembled sibling packages. `HERMES_CONTROL_PYTHON` may name the uv convenience alias in tests because test manifest creation canonicalizes it before pinning; production launch configuration must contain the resolved path.

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
$env:HERMES_CONTROL_PYTHON = '<absolute base python.exe>'
$env:HERMES_CONTROL_WORKER_ROOT = (Resolve-Path ../control-worker).Path
$env:HERMES_CONTROL_INFERENCE_SRC = (Resolve-Path ../inference/src).Path
cargo test --locked --features test-fixture --quiet
cargo clippy --locked --features test-fixture --all-targets --quiet -- -D warnings
cargo fmt --all --check
python -m ruff check scripts
python -m ruff format --check scripts
```

Fourteen tests pass: six unit/admission checks and eight actual/native integrations. Real Python tests cover schema normalization, SQLite persistence across owned worker restart, create/read/list/delete, conflict without retirement, unavailable owner-only methods, schema rejection, source/manifest/state tampering, a second state writer, and a preparation manifest that launches successfully and refuses overwrite. Harmless pinned native peers cover wrong IDs, duplicate keys, unknown fields, truncation, crash, timeout and delayed shutdown tails. Tests verify root/Job/pipe cleanup and survival of an unrelated control process. The resource-host dependency separately passes 28 parser/native ownership tests.

No installed Hermes/Tabby runtime, model, production state or unrelated process is launched or modified by these checks. Native Windows process and canonical-path checks require scoped execution outside the restricted sandbox on this machine. The default build excludes the test peer binary unless `test-fixture` is enabled.
