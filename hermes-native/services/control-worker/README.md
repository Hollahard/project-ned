# Private Python profile control worker

This CPU-only service connects through private stdin/stdout owned by the Rust
resource host. It reuses the existing `hermes_inference.LoadProfile` validation
and stores named settings in an explicitly selected SQLite directory. It does
not start Hermes, Tabby, subprocesses or network listeners; load/generation and
GPU admission are unavailable. A saved profile attests settings syntax only,
not model bytes, runtime compatibility or VRAM requirements.

The companion inference-package change makes HTTP control exports lazy while
preserving their public names. Profile imports use only the Python standard
library. No copied schema, private import namespace or site-packages is needed.

## Launch boundary

The Rust owner supplies an absolute trusted base Python executable, these
literal arguments, and a minimal explicit Windows environment:

```text
-I -S -B -X utf8 <absolute bootstrap.py> --inference-src <absolute inference/src> --state-dir <absolute owned state>
```

The state directory must already exist and equal the working directory; it
must be separate from both source roots. The owner selects this path, never a
renderer request. Source and state directory symlinks/junctions are rejected.
Only `profiles.sqlite3`, its rollback journal and `.worker.lock` are permitted
in existing state. A process-lifetime file lock rejects a second writer. Source
hashes and interpreter provenance remain the Rust launch-receipt authority's
responsibility; these checks are not an operating-system sandbox against other
processes modifying the files.

The child requires isolated/no-site/no-bytecode flags and rejects ambient
`PYTHON*`/`TABBY_*` configuration. It mounts only its finite package modules and the
explicit pure inference modules through a source-only loader under their normal public names. It compiles the actual .py bytes directly, so cached .pyc and extension shadows are ignored. It loads no `.pth`, user-site or
editable-install hooks. No authentication key is needed for private inherited
stdio, and profile fields do not accept credential options. Logging uses
standard Python `logging` at INFO/ERROR on stderr with fixed messages and
stable error codes; stdout contains protocol frames only.

## Protocol

Every frame is UTF-8 JSON followed by one LF, at most 65,536 bytes including LF.
CRLF, malformed UTF-8, duplicate JSON keys, nonfinite numbers, truncated frames,
unknown envelope fields and invalid IDs terminate with a bounded error. The
worker processes one request at a time, with no application queue. It remembers
at most 4,096 unique IDs and asks the owner to restart when that bound is reached.
The native owner additionally bounds pipe buffering and deadlines.

First stdout frame, after state opens successfully:

```json
{"type":"ready","protocol":"hermes-control-v1","service":"hermes-control-worker","runtime_attached":false}
```

Requests are exactly `{"id":"r1","method":"runtime.status","params":{}}`.
IDs match `[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`; Rust generates them. Duplicate IDs
return `DUPLICATE_ID` and never repeat a mutation. Responses are exactly one of:

```json
{"id":"r1","result":{"state":"detached","runtime_attached":false,"admission_allowed":false,"active_profile":null,"engine_observed":false}}
{"id":"r2","error":{"code":"INVALID_PROFILE","message":"The load profile is invalid or exceeds service limits."}}
```

Protocol-envelope failures use `id:null` and exit 2. Operation validation
failures have a valid request ID and leave the worker available. Storage I/O
failures return a fixed error and exit 2; details/paths are not echoed. EOF
closes storage and exits 0. `service.shutdown` responds before exiting 0.
Rust must confirm exit and pipe EOF rather than assuming the acknowledgment
proves cleanup. `service.describe` and `service.shutdown` are owner operations;
the renderer must not choose them through an unrestricted method dispatcher.

| Operation | Exact params | Result |
|---|---|---|
| `service.describe` | `{}` | Protocol/service identity, finite method list, frame/request limits and detached/admission facts |
| `runtime.status` | `{}` | Detached state shown above; no model-unloaded claim |
| `profiles.schema` | `{}` | Dataclass-derived field names/types/defaults, required flags and service size limits |
| `profiles.validate` | `{profile}` | Normalized real `LoadProfile`, `validation_scope:"schema"`, `artifact_verified:false` |
| `profiles.list` | `{}` | `{profiles:[{profile_id,name,revision}]}` summaries, at most 128 |
| `profiles.get` | `{profile_id}` | Saved ID/name/revision plus normalized profile and validation scope |
| `profiles.save` | `{profile_id,name,expected_revision,profile}` | `{profile_id,revision,validation_scope:"schema"}` |
| `profiles.delete` | `{profile_id,expected_revision}` | `{deleted:true,profile_id}` only after an actual deletion |
| `service.shutdown` | `{}` | `{stopping:true}`, followed by exit |

All parameter sets are exact. Profile IDs match
`[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`. Names contain at most 128 UTF-8 bytes;
individual profile strings at most 4,096; a complete normalized profile at
most 16,384 serialized bytes. Listing returns summaries so the entire capped
list stays below the frame limit. Unknown inference/profile knobs are rejected
by the reused schema. Weight quantization remains artifact metadata; this
service cannot convert model weights.

Create requires `expected_revision:null`; update/delete require the last
observed positive revision. SQLite writes use a transaction and synchronous
durability. Initial schema, seed data and version creation also use one explicit
transaction, so interrupted initialization rolls back and can be retried.
A database-wide monotonic clock prevents an old revision from
matching a deleted-and-recreated slug. Conflicts return `REVISION_CONFLICT`
without applying the write. This is a settings store, separate from Hermes
conversation/profile state and the proposed vector memory database.

## Verification

Run from this package using the existing environment and its staged/merged
inference sibling. Use a new temporary-output directory per run:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
$env:HERMES_CONTROL_INFERENCE_SRC = (Resolve-Path ../inference/src).Path
New-Item -ItemType Directory -Force -Path .checks | Out-Null
python -m pytest -o addopts='' -q --basetemp=.checks/new-run --tb=short
python -m ruff check src bootstrap.py tests
python -m ruff format --check src bootstrap.py tests
```

Thirty-four tests cover actual schema reuse, invalid knobs, SQLite reopen/durability,
failure-injected initialization rollback and reopen,
optimistic conflicts and recreation, strict JSONL bounds/IDs, service limits,
an isolated real Python process with exact environment, state ownership and
credential canaries. A subprocess test installs audit tripwires that reject
network/process actions and HTTP/CUDA dependency imports before running the
real entrypoint; it is diagnostic verification, not an OS security sandbox.
The inference package's complete suite separately passes 115 tests, including
a fresh `-I -S` public import and unchanged lazy control exports.

On this machine the restricted Windows sandbox denied canonical path queries
for the sibling staged source; scoped test execution was required. All tests
remain confined to task-created temporary state and harmless CPU workers.
