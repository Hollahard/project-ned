# Opt-in EXL3 live proof

This harness qualifies one explicitly selected EXL3 model using a copied, pinned Tabby runtime and the managed V3 overlay. It is not the desktop application or a benchmark. Read the [live checkpoint](../../../docs/hermes-native-desktop/LIVE-RUNTIME-CHECKPOINT.md) before use.

Activate the project venv. From the repository root, prepare a **new** directory:

```powershell
python ./hermes-native/spikes/model-proof/prepare.py --source 'G:\Project_Ned\runtime\tabbyAPI' --auth-stage ./hermes-native/runtime-packs/tabby-v3 --model 'C:\PyDev\LLM_PC\models\Mistral-Small-3.1-24B-Instruct-2503-exl3' --output ./hermes-native/spikes/model-proof/prepared-new
```

Preparation inventories shard completeness and hashes weights, copied source, interpreter, precompiled extension and bundled compiler/toolkit files. It never loads the engine. Review the receipt before the opt-in launch; an attempted prepared directory cannot be reused:

```powershell
python ./hermes-native/spikes/model-proof/run_live.py --prepared ./hermes-native/spikes/model-proof/prepared-new --backend-src ./hermes-native/services/backend-host/src --inference-src ./hermes-native/services/inference/src --run-gpu-proof
```

The worker uses an explicit environment, ephemeral role credentials, a private Windows Job and isolated caches. The 900-second watchdog retires only owned processes. HTTP observations verify the effective load profile; generation is bounded to 16 tokens, then the harness unloads and retires the worker. It verifies cleanup and scans its artifacts for credential canaries. Whole-GPU telemetry includes other programs; neither HTTP unload nor the measurements prove instant release. The installed dependencies are reused, not fully hashed; this is not OS-enforced write containment. No model copies, V2, vision, fallback switching or hibernation are performed.

Run focused tests from this directory with fresh output locations:

```powershell
$env:HERMES_PROOF_BACKEND_SRC = (Resolve-Path ../../services/backend-host/src).Path
$env:HERMES_PROOF_INFERENCE_SRC = (Resolve-Path ../../services/inference/src).Path
python -m pytest -q --basetemp=.checks/new-test-run
python -m ruff check .
python -m ruff format --check .
```

Windows process and socket ownership checks may require scoped execution permission. Credentials are created in memory, never passed as command-line values or saved into configuration. Prepared candidates, logs and caches are ignored and must not be committed.
