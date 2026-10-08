# Native preview watch service

This is a real filesystem metadata observer for the retained Hermes `watchPreviewFile`, `watchDirectory`, `stopPreviewFileWatch` and `onPreviewFileChanged` contracts. It is independent of Tauri. It performs no file-content reads, writes, subprocess launches, network requests or model operations.

## Integration contract

Create `TrustedRoots::from_host_paths(...)` only from native, verified source routing or a native picker decision. An empty list is valid and denies every watch request. Renderer path arguments **never grant roots**. The host must cap the number of owners; each owner has its own bounded worker, registry and pending events. Keep an `Arc<PreviewWatchOwner>` in the native window/session registry and retire it before its window/context is destroyed or replaced.

| API | Behavior |
| --- | --- |
| `PreviewWatchOwner::new(roots, options)` | Starts one owned observer thread; default 250 ms interval, 64 watches, 4096 immediate directory entries |
| `watch_file(path_or_file_url)` | Requires an existing regular file; returns `{id,path}` |
| `watch_directory(absolute_path)` | Requires an existing directory; returns `{id,path}` |
| `stop(id)` | Stops only this owner's id, clears its queued event/failure, returns whether it existed |
| `dispatch_pending(callback)` | Delivers coalesced `{id,path,url}` events only through the owner-specific callback supplied by the host |
| `take_failures()` | Returns `{id,error}` once when a watch becomes faulted; the host must expose/log this failure without pretending the watch is healthy |
| `retire()` / `Drop` | Permanently rejects new registrations, clears pending events, wakes and joins the owned thread |

Map `watch_file`'s `WatchError::Missing` into the retained `{ok:false,error,message,path?}` missing-file result; all other registration errors remain explicit typed failures. There is no event injection API. `dispatch_pending` must target the registering native window, never an application broadcast. Its callback must be brief, non-panicking, and must not re-enter this owner. The callback runs under the registry lock so `stop` and `retire` return only after in-progress delivery finishes. Events already delivered to a renderer cannot be retracted.

The host should drain pending events approximately every 50–250 ms. Pending changes are deduplicated by watch id and cannot exceed the watch count. Watch errors are likewise bounded, coalesced and contain no raw path. A faulted watch remains registered until stopped and does not silently restart. Registry capacity is 1–128 watches, directory scan limit 1–16384 entries and polling interval 50 ms–5 seconds. Trusted roots are limited to 16.

## Authorization and parity

The host grants metadata observation of a directory subtree, not file reading. The service first rejects path syntax and performs a lexical root containment check, then checks canonical containment and every path component for symlinks/Windows reparse points. It repeats component validation on each scan; a observed replacement link faults the watch. Windows roots must be existing fixed-drive directories; UNC, mapped network drives, removable drives, device paths, alternate data streams, relative paths and parent traversal are denied. Drive classification uses the documented [GetDriveTypeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew) API. Path casing must match the canonical spelling of the granted root's directory components; alternate casing can be conservatively rejected.

Sensitive file exclusions retain the upstream `electron/hardening.ts` intent: `.env` and secret variants, private SSH-key names, `.npmrc`, `.netrc`, `.pypirc`, `.pem`, `.pfx`, `.p12`, `.kdbx`, `.ssh` and `.gnupg`. `.env.example`, `.env.sample`, `.env.dist` and `.env.template` remain permitted. This initial service additionally excludes the entire `.aws` directory. Directory snapshots omit sensitive child names and metadata; they do not use the parent mtime to infer secret-entry churn. Root grants and symlink/UNC restrictions are deliberate additional constraints over the installed Electron implementation.

Polling observes size, modification time and creation time. It matches the upstream storm-fallback approach, with immediate directory-entry metadata in addition to names. File changes produce the retained payload; file disappearance does not emit an event, and a later observed recreation emits again. Atomic replacement is observed when metadata differs. Directory creation, deletion, rename and immediate child-file edits invalidate a directory watch. Descendant traversal is never performed; immediate child-directory metadata may still invalidate the parent after descendant entry churn.

**Limits:** this is invalidation, not an audit/event journal. Multiple edits are coalesced. A change and reversal between polls can be missed, as can a same-size write preserving modification and creation timestamps. It does not wait for file-write completion. Default latency is one 250 ms scan plus host dispatch latency and scan time. Directory work is capped by count, not wall-clock duration. An OS metadata call can still block on a faulty disk/filesystem driver; retirement has no hard OS-I/O deadline. There is no content hashing or recursive watching.

Path checks are not an OS security sandbox and are not atomic with every later metadata syscall. A hostile process racing ancestor replacement can defeat a check/use boundary. No file bytes are exposed by this service. Every future file read/write capability must independently enforce authorization; a watch receipt is never a read token. A same-label replacement renderer must get a new native owner after the old owner is retired.

## Verification

Verified on Windows using Rust/Cargo 1.99.0 on 2026-10-08. Sixteen real filesystem fixture tests passed (4.04 seconds), with Clippy warnings denied and formatting clean. They cover real file/directory events, Unicode/file URLs, two owners watching one file, owner-scoped stop, queued-event cancellation, rapid owner retirement, creation/deletion/rename/replacement, no recursion, zero grants, outside-root/missing/syntax/type failures, sensitive paths, bounds/coalescing, one-time fault reporting, a concurrent delivery/stop barrier, actual native symlink replacement and teardown after callback panic. All fixture files live below this package's `.checks` and were cleaned after the run. No tests were skipped.

The initial teardown test exposed a race when retirement happened before the observer entered its first wait. Checking retirement before the wait fixed it; the final suite verifies the fix. The Windows sandbox denied Rust canonical-path access, so the final native fixture checks ran with a scoped elevation for this isolated package.

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
& .\hermes-native\services\preview-watch\run-tests.ps1
```

The runner requires an active virtual environment and performs these exact checks with an ignored log:

```text
cargo fmt --manifest-path Cargo.toml --check
cargo test --offline --locked --quiet --manifest-path Cargo.toml -- --test-threads=1
cargo clippy --offline --locked --quiet --manifest-path Cargo.toml --all-targets -- -D warnings
```

The reference contract was inspected at Hermes commit `649d6c0391029f35959cfbc240eb3534a6667cf5`: `apps/desktop/electron/preview-file-watch.ts`, `main.ts` watch handlers, `hardening.ts`, and `apps/desktop/src/global.d.ts`. Native shell wiring, a retained-UI run and application-level renderer lifecycle handling are separate integration gates.
