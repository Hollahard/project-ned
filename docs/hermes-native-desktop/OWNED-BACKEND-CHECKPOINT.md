# Rust-owned retained HTTP checkpoint — 2026-10-08

This continuation follows native-profile checkpoint `d175161356f0933c1763e76236d6cf504a4025c7`. It moves the retained HTTP diagnostic's backend process and authenticated connection ownership into Rust. The production Tauri shell still has no Hermes backend or gateway connection; no connection descriptor or readiness state is fabricated.

## Ownership before authentication

The new `services/owned-http` client opens a fresh connection to `127.0.0.1` for each finite diagnostic request. Before sending HTTP bytes, it reads the connected socket's local and remote endpoints, finds the unique reversed ESTABLISHED tuple in the Windows TCP owner table, opens that observed process with query-only rights, and checks membership in the exact private Windows Job. It never adopts or kills a process by its PID. A native test proves an unrelated listener receives zero HTTP application bytes and survives retirement of the task's own process family.

The resource host adds only a read-only observed-PID membership operation. Lifecycle contention and requested retirement fail closed. Process launch still uses the canonical executable, suspended creation, explicit inherited handles and a clean environment, with assignment to the private Job before execution resumes. The diagnostic uses captured output, not the profile worker's framed protocol.

The HTTP client accepts only the reviewed routes, query spellings, GET requests and one forbidden POST case used for testing. Only the diagnostic token header is caller-controlled. It has no proxy, redirects, DNS lookup, cookie storage, connection reuse or retry. A single deadline covers connection, ownership observation, request writes, response parsing and EOF. Header/body size, header count, chunk overhead and TCP table allocation are bounded. Static errors never include response bodies or credentials. This finite client is not a general production HTTP or streaming-chat implementation.

## Retained handler proof

`spikes/retained-http` prepares explicit source/interpreter pins and uses an ephemeral environment-only credential. Rust owns the diagnostic backend; the Python outer script is only a watchdog for the exact Rust process handle. The diagnostic mounts the existing configuration and session-list handlers from the pinned Hermes source in a fresh synthetic home. It does not call the stock server entry point, initialize the gateway, start inference, or operate on installed user state.

The proof checks missing, wrong and duplicate authentication; rejected routes, profile overrides, query values and methods; actual configuration/session responses; and an authenticated source/process identity response. It then forces retirement of its private Job because this diagnostic has no cooperative shutdown endpoint. Forced retirement is labeled explicitly. Completion requires root exit, empty Job membership and both pipe EOFs. An intentional failure after readiness verifies cleanup without converting application failure into success.

Source fingerprints are rechecked afterward. State paths and file bytes are scanned for the ephemeral credentials under explicit size/count bounds; reports contain reviewed facts and static errors rather than raw responses or child logs. Installed dependency code is reused and is not fully attested. These checks are diagnostic tripwires, not an OS sandbox or a guarantee against a concurrent privileged filesystem writer.

## Windows compatibility findings

The Rust owner revealed two path-representation differences that the previous Python owner did not exercise. CPython can report a verbatim `\\?\C:\...` base directory while imported standard-library files use ordinary `C:\...` spelling. The diagnostic path policy now compares resolved drive paths in a consistent namespace without stripping significant trailing dots or spaces. Tests preserve credential-name denial, outside-root rejection, nonexistent-write handling and reparse escape rejection.

The retained session reader converts a database path with `Path.resolve().as_uri()`. A verbatim state path produced a URI with `%3F` as its authority rather than an ordinary local-file URI. The proof therefore uses an explicitly limited, short synthetic-state spelling after proving canonical identity and rejecting names whose meaning could change. Exact cwd/home identity uses the actual directories. Shared process-launch semantics and retained handlers stay unchanged. Production long-path SQLite URI behavior remains a separate compatibility gate.

The preparer exports the finite diagnostic helper closure into a fresh source-only location and checks its copied bytes. It does not reuse or delete the development checkout's bytecode caches. Candidate/helper import shadows are rejected before launch. Launch-time hashes and clean copies do not constitute complete dependency attestation.

## Verification and next boundary

The final managed-worktree foundation run passed **39 groups and 393 component tests**, including seven owned-HTTP tests, 29 resource-host tests and 56 backend-host tests. Renderer build, source/dependency preservation, native child-WebView checks, formatting and denied-warning lint checks passed. [Foundation receipt](implementation-evidence/owned-http-foundation-worktree.json) records this run separately from the previous native-profile milestone.

The retained diagnostic's five Rust tests, formatting and denied-warning Clippy checks passed separately. The [actual retained HTTP run](implementation-evidence/owned-http-success-worktree.json) passed all 12 assertions in 4.405 seconds. The [intentional failure run](implementation-evidence/owned-http-failure-cleanup-worktree.json) preserved its failed application status while verifying cleanup in 4.133 seconds. Both used executable SHA-256 `616805171d1f255dfa982f9af8aa4a958e83f9aa174eff013936e978c256111d`, rechecked source pins and completed credential scans over 280,335 synthetic-state bytes.

The diagnostic records helper policy `resolved-drive-comparison-v2`, helper-policy hash `41b341ecfc194e2c5011953a02a07e1dd006b4258073763e9bddd10afbdc9e1a` and state adapter `short-equivalent-dos-state-v1`. The unchanged candidate manifest is `b1bb07041d7794dec27ba18a0ee0e50e7ac9c8dff19de8fb659fe9ceb6108445`, derived from Hermes `649d6c0391029f35959cfbc240eb3534a6667cf5`. Installed Python 3.11 dependencies remain reused, rather than declared fully attested.

Exact reproduction commands are in the [retained Rust HTTP runner](../../hermes-native/spikes/retained-http/README.md), [finite owned HTTP client](../../hermes-native/services/owned-http/README.md) and [foundation verifier](../../hermes-native/scripts/Verify-Foundation.ps1). Each live diagnostic requires a fresh output/helper directory; historical prepared directories must not be reused. The production desktop-shell source and its previous native-profile evidence are unchanged by this slice; its full native UI suite was not repeated for this diagnostic-only change.

The next production backend slice must preserve these ownership guarantees while deliberately restoring real gateway startup, connection generations, cancellation, settings/session semantics and source routing. Existing browser/terminal/credential and runtime ownership gates remain open. This checkpoint does not establish desktop parity or complete the saved-profile model profiler, vector memory, Gaming Mode or Windows installer.

A separate hidden-WebView capture investigation passed profile interaction and process-cleanup checks but returned stale initial-frame pixels. Its prototype was not integrated and no screenshot was accepted as profile or visual-parity evidence. A future visible interactive validation must verify the actual rendered frame and focus behavior; hidden DOM assertions alone do not satisfy that gate.
