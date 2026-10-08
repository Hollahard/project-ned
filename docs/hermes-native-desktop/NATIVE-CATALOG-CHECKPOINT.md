# Native catalog integration checkpoint — 2026-10-08

The retained **Local model profiles** form now has an **Inspect metadata** action backed by a separate Rust-owned Python catalog process. The existing saved-profile service remains responsible for settings and revisions. Inspection reports declared metadata and incomplete artifacts without changing settings, loading weights or presenting a model as runtime-ready.

## Ownership and UI behavior

The Tauri `hermes_model_inspect {modelPath}` command checks the exact main window, bound HWND and bundled origin. It admits one request before scheduling blocking work. The independently reachable owner exists before dispatch, so closing or replacing the document can retire queued or running work. Ordinary hash-route navigation preserves the owner; full navigation and app exit retire it. Late results cannot reach a replacement document.

The optional `HERMES_NATIVE_CATALOG_CONFIG` selects a host-owned receipt. Absent or invalid configuration leaves inspection unavailable. The receipt pins the resolved base Python executable, bootstrap and five catalog source modules; it also names a private working directory, one to eight explicit root grants, a work deadline of at most 30 seconds and separate cleanup deadline of at most five seconds. The renderer cannot choose these values. Entering a folder path does not grant access to its parent.

Before reading the requested model, the host requires one immediate child of a granted local DOS path and rejects reparse/network/device paths. The current host expects native Windows backslash spelling. It launches a source-only `-I -S -B -X utf8` inspector in a private Job using an explicit minimal environment. Cached bytecode and native-extension shadows in the catalog package are ignored. It imports no model code, engine, tokenizer library or GPU runtime.

A valid result is one exact bounded LF-delimited JSON frame, at most 64 KiB, with required nullable compatibility fields. All missing shard basenames are retained within the 64-shard limit; diagnostics are capped at 32 with explicit truncation. Delivery requires root exit zero, both output EOFs, completed pipe drainers, no trailing complete or partial frame and an empty owned Job. A failed request can be retried only after verified cleanup; incomplete cleanup permanently retires that owner. These are bounded process/protocol rules, not an OS sandbox, atomic filesystem snapshot or hard real-time guarantee for kernel calls. Python DLL/stdlib bytes are not completely attested.

The form displays inspection status, declared architecture/format/bits, observed and indexed tensor counts, every missing shard and the limited fingerprint scope. It clears results when the path or selected profile changes. Captured-path and generation checks discard late responses after edits, reset, selection or unmount. Inspection never fills defaults, changes saved fields/revisions, registers an artifact or loads a model. `runtime_compatible` remains null, `load_certified` false and payload bytes read zero. Header/metadata fingerprints exclude weight contents.

See the [catalog owner](../../hermes-native/services/catalog-host/README.md), [shell setup and commands](../../hermes-native/apps/desktop-shell/README.md) and [renderer behavior](../../hermes-native/apps/desktop-ui/README.md). A native picker and persistent user-facing grant management remain follow-up work.

## Verified integrated result

The final worktree passed **48 foundation groups and 478 component tests**, including the renderer build and bounded native component fixtures. This adds 17 Rust catalog-host tests and six Python bootstrap/configuration tests to the previously verified components. The [foundation receipt](implementation-evidence/native-catalog-foundation-worktree.json) retains per-group timing and test counts. Shell verification separately passed seven Rust tests in each default/fixture configuration, 12 transport tests, two packaging tests, formatting and strict Clippy; repeated configurations are not added to the 478 count.

All 11 native modes passed against the same development executable, SHA-256 `24b0e8a3fc2bd90b812b4ce2446051482d837ae87e93c69fb48075c1ab41a309`:

| Mode | Passed assertions |
|---|---:|
| Native binding | 19 |
| Retained bootstrap | 11 |
| Preview delivery | 14 |
| Preview document replacement | 6 |
| Control unavailable | 4 |
| Control create / reopen | 13 / 13 |
| Retained profile form | 22 |
| Catalog command / unavailable | 9 / 2 |
| Retained profile form with inspection | 29 |
| **Total** | **142** |

The [native receipt](implementation-evidence/native-catalog-native-worktree.json) records each assertion and cleanup result. Every outer fixture verified its own Job/root/pipe cleanup. Configured control workers shut down cooperatively; configured catalog workers exited zero with both pipe EOFs and empty Job membership. Absent services have null cleanup reports and are not claimed as launched.

The 29-check form run inspected real synthetic partial metadata through Tauri and the owned catalog process, displayed its missing shard, preserved saved fields/revision and discarded late results after editing/selection. A fixture-only delivery gate holds an actual already-inspected and cleaned result for at most five seconds, then waits for React promise settlement before asserting the stale result was ignored. It fabricates no inspection DTO and is absent from default builds.

The [renderer guard](implementation-evidence/native-catalog-renderer-build.json) reports **2,986 unchanged retained source inputs** and **110 pinned direct dependencies** at Hermes `649d6c0391029f35959cfbc240eb3534a6667cf5`. The source aggregate remains `7a6c24f0b7dd1383baac61169eafedb7cb212229f1775b9eb667b6a167e7b968`; [1,088 packaged assets](implementation-evidence/native-catalog-asset-package.json) and the [integration source receipt](implementation-evidence/native-catalog-source-receipt.json) identify this build. Hidden DOM checks establish functional behavior, not screenshots, visual parity, accessibility or keyboard/focus fidelity.

## User-model observations through the Rust owner

The same catalog owner inspected all three user-granted model folders through its CLI example. Native UI fixtures used synthetic artifacts; the real folders were exercised through the owned CLI, not selected in the UI. The [reports and cleanup receipts](implementation-evidence/native-catalog-real-models-worktree.json) record:

| Model folder | Status | Elapsed | Cleanup |
|---|---|---:|---|
| Mistral-Small-3.1-24B-Instruct-2503-exl3 | `metadata_inspected` | 0.297 s | Verified |
| Qwen3-30B-A3B-Instruct-2507 | `metadata_inspected` | 1.171 s | Verified |
| Qwen3.5-35B-A3B-exl3-clean | `incomplete` | 2.282 s | Verified |

Qwen3.5 still lacks `model-00001-of-00003.safetensors`. All three retained zero weight-payload reads, unknown runtime compatibility and no load certification. No model file was copied or changed. CLI success means a valid truthful inspection report, which can be incomplete; it does not mean successful inference.

## Resume boundary

The saved settings and read-only inspection path are integrated. The production shell still reports Hermes backend unavailable. The [next backend integration plan](NEXT-BACKEND-INTEGRATION.md) and [native socket acceptance plan](NATIVE-SOCKET-TEST-PLAN.md) describe the next work: an owned socket transport, managed retained startup without stock side effects, actual gateway RPC, then a real agent conversation. Those plans do not assert completed gateway integration.

The separate [Qwen3 EXL3 proof](QWEN3-RUNTIME-CHECKPOINT.md) demonstrated bounded load, completion, unload and owned cleanup on the user's GPU. It did not connect this UI to inference or certify chat templates/tool calling. Vector memory, manual inference/context profiling, quantization conversion, ExLlamaV2 qualification, Gaming Mode/fallback/hibernation, full browser/terminal parity and a signed Windows installer remain open. Do not reuse consumed GPU proof directories or start stock Hermes supervisors during continuation.
