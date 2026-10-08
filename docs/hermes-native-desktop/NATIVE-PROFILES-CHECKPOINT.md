# Native preview and saved-profile checkpoint — 2026-10-08

This continuation starts at `44cae2cf140afd4ca153ecb14cdf310274098c96`. The retained Hermes interface now mounts in the independent Tauri shell, and a new settings contribution saves model load profiles through a Rust-owned Python worker and SQLite. The shell still reports that the Hermes agent backend is unavailable. This is a verified development milestone, not a finished desktop replacement or installer.

## Integrated behavior

The original renderer remains pinned to `649d6c0391029f35959cfbc240eb3534a6667cf5`: 2,986 retained source inputs and aggregate `7a6c24f0b7dd1383baac61169eafedb7cb212229f1775b9eb667b6a167e7b968`, with 110 pinned direct dependencies. The wrapper registers the profile page through the existing plugin/settings contribution APIs. It does not edit the retained source. Source preservation is not proof of complete visual or functional parity.

The host adapter exposes 16 reviewed methods and five retained events. Thirteen backend-related methods reject with readable capability-unavailable errors. Three preview methods have a real Rust producer: file watch, directory watch and stop. Native grants are empty by default; fixtures grant only fresh task-owned roots. File changes reach the exact owning native window and document. An adversarial listener in another window receives none. Hash routing preserves the owner; full document navigation permanently retires its watches. Automatically recreating that owner after reload remains future work.

Preview polling uses bounded watch and directory-entry counts. It does not read file content or recurse. Polling can miss a same-size rewrite whose timestamp is unchanged, and filesystem calls have no hard real-time guarantee. A direct WebView delivery channel is necessary because Tauri application events can reach another window's global listener even with a window target. The native envelope includes the document identifier so a replacement page rejects queued old-page events.

The profile contribution is `native-model-profiles:profiles` under the retained Settings plugin page. Users can list, select, validate, create, update and delete named profiles. Settings include model identity/path, context, cache size and precision, chunk size, batch size and vision. Save and delete use optimistic revisions; deletion requires a second click. Errors are bounded, static messages. A failed connection offers an explicit retry; stale responses from previous mounts or clients cannot replace current UI state.

Validation here is the existing `LoadProfile` schema only. It does not inspect a model artifact, quantify VRAM, run inference, quantize weights or certify a selected context. Cache precision is not model weight quantization. Saved profiles are the first part of the requested model profiler, not its benchmark or runtime activation interface.

## Process and persistence design

`services/resource-host` now provides bounded captured output, readiness parsing and framed stdio in addition to Windows Job ownership. Child creation remains suspended until assignment to the private kill-on-close Job. Only the exact intended stdio handles are inherited. Frame sizes, queue depths, pending input and deadlines are bounded. Retirement closes admission before waiting for cleanup.

`services/control-host` launches a host-selected, hash-pinned base Python interpreter and finite source set. The renderer cannot choose executables, launch arguments, environment, source roots or state paths. The child uses isolated Python startup and a source-only importer; no model, network listener, site package or GPU runtime is started. An operation permit is acquired before scheduling blocking work, so excess requests return busy instead of accumulating tasks.

`services/control-worker` owns a separate SQLite settings directory and lifetime lease. Schema initialization and profile updates are transactional. Revisions continue increasing across deletion/recreation, preventing an old editor from overwriting a newly recreated record. The service exposes seven finite public status/profile operations. Describe and shutdown remain owner-only protocol operations. The status truthfully reports a detached inference runtime.

Protocol corruption, unknown response shapes, wrong IDs, overflow, timeout and child failure retire the worker generation. Ordinary validation and revision conflicts leave it healthy. Uncertain mutations are never automatically replayed. The host verifies root exit, both pipe EOFs, drained protocol data and zero Job members before reporting cooperative cleanup. Failed startup cannot inherit a false success receipt from an empty fallback state.

Launch-time hashes do not pin all Python DLL/standard-library bytes or create an OS security sandbox. Production installation, filesystem permissions, recovery, credentials and runtime pack ownership remain separate gates. The Python backend owner remains a diagnostic fixture helper; production control ownership in this milestone belongs to Rust.

## Verification

Eight bounded native fixture modes passed against the same consolidated executable in fresh WebView profiles:

| Mode | Checks | Observation |
| --- | ---: | --- |
| binding | 19 | Native injection, honest unavailable responses, IPC/event ACL and unsubscribe |
| retained | 11 | Actual root and contribution shell mounted with readable backend-unavailable recovery dialog; no React crash or unhandled error |
| preview | 14 | Real file/directory mutation, stop barriers, exact-window delivery and permanent retirement |
| preview-reload | 6 | Hash navigation, document replacement and queued-event rejection |
| control-unavailable | 4 | Missing host configuration never fabricates a worker |
| control-create | 13 | Real native schema validation, SQLite create/read/list and revision conflict |
| control-reopen | 13 | Persistence through a new owned worker, update and delete |
| profiles | 22 | Actual retained Settings navigation and React form validate/create/read/update/confirmed-delete through native Rust and Python |

Every native run verified outer fixture Job cleanup. Configured profile runs additionally verified the Rust-owned worker's cooperative shutdown, root exit code zero, both EOFs and empty Job. These assertions are distinct from component test counts and from the prior EXL3 GPU observation. No inference runtime or Hermes agent backend started in these runs.

The [final worktree regression summary](implementation-evidence/native-profiles-foundation-worktree.json) passes all 36 groups and 379 component tests. The [native evidence](implementation-evidence/native-profiles-native-worktree.json) records 102 assertions across the eight modes on one executable. The [asset package](implementation-evidence/native-profiles-asset-package.json) contains 1,085 files, and the [source manifest](implementation-evidence/native-profiles-source-manifest.json) identifies the assembled source bytes. Shell checks include seven Rust tests, eleven transport tests, two asset-packaging tests, default/all-feature strict Clippy and formatting. Component checks cover captured/framed workers, preview ownership, native Python control, atomic profile persistence, existing inference contracts and retained settings integration. Historical test counts in older checkpoints remain historical.

## Reproduction and continuation

Activate the project environment and run `hermes-native/scripts/Verify-Foundation.ps1` with the existing pinned upstream and Tabby paths, `-BuildRenderer -NativeFixtures`. That runner covers CPU/native component checks and intentionally does not start GPU work. Full Tauri packaging and native UI fixtures use the separate [shell instructions](../../hermes-native/apps/desktop-shell/README.md). Prepare a new control manifest/state directory with `services/control-host/scripts/prepare_config.py`; reuse only that manifest's SQLite state for the explicit create/reopen persistence pair. Never reuse a consumed GPU-proof directory.

The next backend gate is to consolidate authenticated loopback connection ownership into Rust, then attach actual retained HTTP and gateway behavior without fabricating a connection descriptor. The existing retained HTTP subset remains a diagnostic with synthetic state, not stock Hermes startup. The next model-profiler gates are artifact verification, a separately owned ExLlama runtime, explicit load/unload and manual measurements. Vector memory, V2 qualification, Gaming Mode admission/drain/release/recovery, small-model fallback, hibernation, browser/terminal integration and installer packaging remain open.

The prior [architecture](ARCHITECTURE.md), [live runtime checkpoint](LIVE-RUNTIME-CHECKPOINT.md) and [native binding checkpoint](NATIVE-BINDING-CHECKPOINT.md) retain their evidence and scope. Existing main-checkout user edits remain outside this managed worktree's changes.
