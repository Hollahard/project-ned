# Qwen3 EXL3 runtime checkpoint — 2026-10-08

Following the [read-only model catalog](MODEL-CATALOG-CHECKPOINT.md), the existing opt-in GPU harness successfully loaded, generated with and unloaded the complete `Qwen3-30B-A3B-Instruct-2507` model on this Windows machine. This is a second explicit EXL3 runtime observation after the earlier [Mistral test](LIVE-RUNTIME-CHECKPOINT.md), and is separate from both the metadata inspector and the desktop profile service.

## Observed result

The [GPU report](implementation-evidence/qwen3-exl3-proof.json) passed at 18:31:34 UTC on 8 October 2026. The [selected attestation](implementation-evidence/qwen3-exl3-attestation.json) records full pre-launch hashes of required weights/metadata, the runtime/interpreter/toolchain identities and exact proof sources. The local files stayed in place; no model was copied or modified.

| Operation | Observation |
|---|---|
| Explicit authentication and no autoload | Passed before model load |
| Load | 21.375 seconds; actual model identity and effective settings verified |
| Settings | 2,048 context and cache, FP16 cache, batch 1, chunk 256, vision/drafting disabled |
| Generation | Nonempty output, 16 completion tokens, 6.125 seconds; token-limit finish |
| Unload | 0.219 seconds; model absence verified |
| Whole-GPU used memory | 2,069 MiB before worker; 21,642 MiB loaded; 2,812 MiB after unload; 2,045 MiB after owned process exit |
| Cleanup | Owned Job empty, root exited, both pipes drained and listener closed |
| Preservation | Model names/sizes/mtimes, small metadata hashes and managed source hashes unchanged |
| Credential scan | Complete over 237,592,349 proof-owned bytes; no token file or credential match |

Runtime pack: `tabby-v3:2fd6cc76203a66e13042daf7d76e5898b21c1ad8:hermes-native-observation-v1`. Hardware: RTX 5090, 32,607 MiB reported, driver 617.42. The base Python 3.12 interpreter, precompiled ExLlamaV3 extension and bundled Triton compiler/toolkit were explicitly pinned; installed dependencies were reused and are not fully attested. This follows the same runtime setup as the earlier Mistral proof.

Full required weight contents were hashed before launch. Afterward, preservation checks compare names/sizes/mtimes and small metadata hashes; they do not reread all tensor payloads. This is not immutable filesystem enforcement. The catalog's metadata fingerprint remains a different, explicitly weaker identifier and its inspection reports retain `load_certified: false` and `runtime_compatible: null`.

## Verification and reproduction

The harness's internal artifact label was generalized from `local-mistral-proof` to `local-exl3-proof`. Actual identity still comes from the receipt's model path/name and content revision; no effective settings or runtime behavior changed. The isolated harness passed its 11 tests, Ruff and formatting checks before that one-line change was integrated and the real GPU run performed. This targeted change did not repeat the unrelated foundation/native UI suites.

Use [model-proof](../../hermes-native/spikes/model-proof/README.md) with a **new** prepared directory and explicitly selected Qwen3 path. Preparation and GPU launch are separate steps so the receipt can be inspected before launch:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
python ./hermes-native/spikes/model-proof/prepare.py --source 'G:\Project_Ned\runtime\tabbyAPI' --auth-stage ./hermes-native/runtime-packs/tabby-v3 --model 'C:\PyDev\LLM_PC\models\Qwen3-30B-A3B-Instruct-2507' --output '<new absolute prepared directory>'
python ./hermes-native/spikes/model-proof/run_live.py --prepared '<same reviewed prepared directory>' --backend-src ./hermes-native/services/backend-host/src --inference-src ./hermes-native/services/inference/src --run-gpu-proof
```

The completed `hermes-qwen3-proof-prepared-01` directory is consumed and must not be reused. A 900-second watchdog limits the proof and retires only its owned process tree. Credentials are ephemeral environment values; installed source and unrelated GPU processes are not controlled by the harness.

## Remaining boundary

The generation uses the completions endpoint with a bounded prompt. It does not qualify conversational templates, tool calls, vision, long-context operation, alternate cache formats, concurrency or every model with the same architecture. These single-run times include local cold/warm effects and are not throughput benchmarks.

GPU telemetry includes other desktop allocations. Observed unload time and later memory samples do not prove instant VRAM evacuation or a durable Gaming Mode transaction. The GPU harness still uses the earlier Python ownership transport with listener-membership snapshots; it is not the newer finite Rust socket-bound HTTP diagnostic, and production runtime routing remains a separate gate. No runtime was connected to the saved-profile UI, no profile was automatically marked ready, and no fallback model or hibernation path was exercised.
