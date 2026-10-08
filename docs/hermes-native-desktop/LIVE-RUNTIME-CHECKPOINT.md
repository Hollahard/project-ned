# Live runtime checkpoint — 2026-10-08

This extends foundation commit `666ff76a5ddc59aecfabb66c7f0eaba687c7dc3d`. The earlier 26-group/256-test foundation evidence remains historical and unchanged. This checkpoint adds opt-in diagnostic harnesses and measured runtime evidence; it does not deliver the replacement desktop application.

## Real EXL3 qualification

The [GPU report](implementation-evidence/live-exl3-proof.json) passed at 03:57:01 UTC (11:57 PM EDT, October 7). It used the existing `C:\PyDev\LLM_PC\models\Mistral-Small-3.1-24B-Instruct-2503-exl3` weights in place, an exported Tabby candidate at `2fd6cc76203a66e13042daf7d76e5898b21c1ad8`, and the `hermes-native-observation-v1` overlay. Installed source and model metadata were not changed. Required weights were fully hashed before launch; post-run checks compare names, sizes, mtimes and small metadata hashes rather than rereading every tensor.

| Operation | Observed result |
| --- | --- |
| Authentication/no autoload | Passed, before explicit model load |
| Load | 19.938 seconds; actual model identity/settings verified |
| Settings | 2,048 context and FP16 cache, batch 1, chunk 256, vision/drafting disabled |
| Generation | Nonempty output, 16 completion tokens, 6.141 seconds; stopped at token limit |
| Unload | 0.156 seconds; model absence verified |
| Whole-GPU memory | 2,832 MiB before worker; 18,080 MiB loaded; 2,870 MiB after unload; 2,188 MiB after process exit settled |
| Retirement | Owned Job empty, root exited, pipes drained, listener closed |
| Credential scan | Complete over 236,223,251 proof-owned bytes; no token file or credential canary match |

Telemetry includes unrelated desktop allocations. Unload latency is one observation, not an instant-release guarantee, dedicated process VRAM measurement, performance benchmark, or a Gaming Mode implementation. The reused installed dependency tree is not fully attested, and the harness does not enforce filesystem immutability through an OS sandbox.

Runtime: RTX 5090 (32,607 MiB reported), driver 617.42, Python 3.12.13, ExLlamaV3 1.5.4+cu132.torch2.11.0, Torch 2.11.0+cu130, Triton Windows 3.8.0.post29. [Selected attestation](implementation-evidence/live-exl3-attestation.json) records model and compiler/toolkit hashes. Prepared attempts 03 and 06 failed closed and retired their workers: the first exposed a Windows venv redirector environment conflict; the second exposed missing explicit Triton compiler discovery. Neither established a successful generation. Attempt 07 used the attested base interpreter with `-I -S -B`, explicit site-packages and explicit `CC`/`CUDA_PATH`. Triton kernel compilation used its bundled compiler; the ExLlama extension was precompiled, with fallback compilation rejected. The supported compiler configuration is documented by [Triton Windows](https://github.com/triton-lang/triton-windows).

The transport checks owned listener membership before sending credentials and before each request. These checks are TCP ownership snapshots, not cryptographic identity or proof bound to each established connection. Consolidating stronger connection verification into the production owner remains a gate.

## Retained Hermes HTTP proof

The [HTTP report](implementation-evidence/retained-http-proof.json) exercises the actual, unchanged upstream `get_config` and `get_sessions` handlers from Hermes `649d6c0391029f35959cfbc240eb3534a6667cf5`. It uses a fresh synthetic home and a minimal owned ASGI host, not stock `hermes serve`, the gateway, or chat execution. Nine authentication/rejection checks passed. The exact established socket was checked for membership in the private Job before credential headers were sent. Cleanup passed, no credential bytes persisted, and diagnostic policy recorded no violations.

The [source manifest](implementation-evidence/retained-http-source-manifest.json) inventories 1,980 copied tracked Python files and four exact hash-guarded diagnostic changes: two Windows platform detections avoid subprocess probes, provider discovery returns early, and dotenv secret loading returns an empty result. Handler bodies and profile-scoping helpers remain unchanged. `HERMES_SKIP_CHMOD=1` uses an upstream override for this synthetic Windows home. Named profiles, query-profile selection, write routes and every unlisted endpoint are rejected before dispatch. Synthetic session/default configuration files are created, so this is not a claim that the handlers perform no writes.

No stock bootstrap, rendezvous publication, global reaper, provider/plugin activation, MCP, generation or update lifecycle is enabled. The transitive import closure is recorded in the report; importing helper modules is not activation of those services. Python audit hooks provide additional tripwires, not an OS sandbox ([Python audit-hook limitations](https://docs.python.org/3.12/library/sys.html#sys.addaudithook)). Native extensions and unreviewed code require stronger production isolation. This diagnostic package must not be advertised as full Hermes startup parity.

## Verification and next implementation gate

Staged backend tests: **50 passed**, including the prior 29 host tests and 21 diagnostic policy cases. GPU harness: **11 passed**. Ruff checks and formatting checks passed for both components. Final worktree verification is recorded separately when integrating this checkpoint; the historical foundation test total is not silently replaced or added to these counts.

The reproducible source is in [model-proof](../../hermes-native/spikes/model-proof/README.md) and [backend diagnostics](../../hermes-native/services/backend-host/diagnostics/README.md). Proof runs are opt-in and use new state/prepared directories. Weights, copied upstream source, caches and runtime environments are excluded from Git.

Next, bind the retained renderer's typed host subset to one Rust owner and add authenticated managed backend routing. Keep unsupported native methods explicit. Consolidate captured I/O and connection ownership into the Rust host before shipping a supervisor. Establish full retained chat/WebSocket startup behavior and baseline visual comparisons before declaring desktop parity. Then implement durable model profiles and a generation-draining unload transaction for Gaming Mode, with measured release and recovery. Vector memory, V2 qualification, fallback-model switching, hibernation, Tauri packaging and the Windows installer remain open; a successful EXL3 smoke test does not close those gates.
