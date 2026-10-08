# Hermes native inference: M1 V3 control foundation

This standalone Python package implements a narrow control seam for the **managed** pinned TabbyAPI V3 variant. It has no dependency on Project Friday, no CUDA imports, no process launcher, and no application startup side effects. Stock Tabby is deliberately unsupported for readiness verification because its model card does not reveal whether drafting is enabled.

The inspected upstream contract is TabbyAPI commit `2fd6cc76203a66e13042daf7d76e5898b21c1ad8`, with the hash-guarded `hermes-native-observation-v1` managed overlay. `RUNTIME_PACK_ID` identifies that combination; the supervisor must also attest the exact overlay file hashes in `overlay-manifest.json`. A version string returned over HTTP cannot establish authenticity. The installed runtime observed during development uses ExLlamaV3 `1.5.4+cu132.torch2.11.0`, Torch `2.11.0+cu130` and Triton Windows `3.8.0.post29`. HTTP tests use `httpx.MockTransport`; optional pinned-source tests execute selected AST nodes with harmless stubs, never importing the engine. These establish control-protocol behavior, not hardware compatibility, GPU performance, VRAM release, engine authenticity, or Hermes desktop parity.

## Interface

- `LoadProfile`: frozen artifact/revision identity plus a relative Tabby model name, expected absolute engine path, context length, cache capacity/precision, batch size, chunk size and vision setting. `from_mapping()` rejects unknown options. Revisions and artifact IDs are opaque catalog identities; the catalog must attest their file hashes.
- `Credentials.from_environment()`: reads `HERMES_TABBY_API_KEY` and `HERMES_TABBY_ADMIN_KEY` without persisting them. Credentials are excluded from `repr`; upstream error bodies are never logged or propagated. This is client credential injection only: stock Tabby server authentication still needs the architecture's separate environment-only startup patch.
- `AdmissionGate.snapshot() -> AdmissionSnapshot(generation, allowed)`: synchronous adapter for the resource authority's current fenced policy. Snapshots must be cheap, fail closed and update on the same event loop before controller work is resumed. The supplied `InMemoryAdmissionGate` starts closed and is only a process-local test/reference implementation.
- `TabbyV3Control.apply(profile)`: serialized model transition with complete load SSE consumption, bounded parsing, effective-settings verification and a final admission-generation check.
- `reconcile(profile)`: observe the pending desired identity/settings after an uncertain operation. It never issues a model load. Absence cannot resolve uncertainty because an upstream detached load may still be running.
- `unload()`: serialized teardown, permitted with admission closed. Confirms the model endpoint reports absence. It makes no statement about VRAM, embeddings, other worker processes or GPU allocations.
- `generation(profile)`: async context manager that holds the same lock for an entire caller-owned generation stream. It verifies actual model/settings before yielding `GenerationLease`. `lease.ensure_valid()` fences forwarding after admission changes. A lease expires on context exit.
- `status()`: immutable local control status. This is not a live GPU health endpoint.
- `aclose()`: closes HTTP handles; never unloads a model or kills a process.

Example integration outline (no embedded credentials):

```python
from hermes_inference import Credentials, TabbyV3Control

# authority implements AdmissionGate; registered_profile is an immutable catalog snapshot.
control = TabbyV3Control(
    base_url=owned_runtime.loopback_origin,
    credentials=Credentials.from_environment(),
    gate=authority,
)
await control.apply(registered_profile)
async with control.generation(registered_profile) as lease:
    lease.ensure_valid()
    # Open the generation request through the broker's own authenticated client.
    # Keep this context alive until the stream closes; check ensure_valid() before
    # forwarding each chunk or admitting another inference/tool round.
```

The application must not expose an unguarded generation path alongside this seam. Tabby's Chat Completions `model` field does not select a model: the broker resolves its immutable alias first and must use the matching lease. The resource authority closes admission before awaiting quiescence and cancels its owned generation tasks; merely changing a synchronous snapshot cannot interrupt arbitrary I/O already executing in caller code.

## Supported load contract

| Profile field | Tabby request | Verified observation |
| --- | --- | --- |
| `model_name` | `model_name` | Load alias resolves to `expected_model_path`; model card ID must match the resolved directory basename |
| `expected_model_path` | Not forwarded | Absolute path comparison, including Windows separators/case |
| `context_length` | `max_seq_len` | Model parameters and props `n_ctx` |
| `cache_size` | `cache_size` | Model parameters; positive multiple of 256, at least context length |
| `cache_mode` | `cache_mode` | Model parameters; FP16, Q4/Q6/Q8 or integer `K,V` bits 2–8 |
| `max_batch_size` | `max_batch_size` | Model parameters and props `total_slots` |
| `chunk_size` | `chunk_size` | Model parameters; positive multiple of 256, rejected before I/O otherwise |
| `vision` | `vision` | Model parameters and props modalities |

Q4/Q6/Q8 user-input aliases normalize to `4,4`/`6,6`/`8,8`. Reported cache modes are interpreted strictly: upstream only recognizes uppercase aliases or an anchored K,V pair and otherwise silently uses FP16. A raw report such as `q6` or ` 6,6 ` is therefore rejected, even though those inputs can be normalized before sending.

The load payload explicitly selects `exllamav3` and requests disabled drafting. Because model-folder overrides win over that request and stock `parameters.draft` stays null even when drafting is active, READY requires the managed `parameters.hermes_native_draft_enabled` field to be the actual boolean `false`. Missing, null, or wrongly typed observations raise `UNSUPPORTED_MANAGED_RUNTIME`; true or an observed draft SSE component fails effective-settings verification. The overlay computes this field from the backend's actual `use_draft_model` and `ngram_match_min` state, covering separate draft models, MTP, and n-gram drafting.

This does not establish that all other inference-affecting server configuration is absent: trusted runtime configuration and artifact validation remain authority prerequisites. GPU placement, tool templates, reasoning options, MoE offload, conversion, samplers and saved-profile persistence are outside this narrow profile schema. Unknown controls are rejected rather than represented as applied. A catalog load alias may differ from the resolved model directory name; identity uses the exact expected absolute path and its basename, with Windows case handling, rather than trusting the alias or basename alone.

Same-profile `apply()` reverifies without loading again. Any changed immutable profile or a newly attached resident model is unloaded before loading the desired profile, including a changed context/cache on the same path. This avoids Tabby's same-path load shortcut. The old profile is not falsely retained as active after a failed swap, and the package does not automatically reload it.

The adapter reads `/v1/model`, `/props`, then `/v1/model` again and rejects an inconsistent observation. Lexical path comparison cannot detect symlink/reparse-point changes or changed weights. These endpoint reads cannot make an externally writable engine atomic. The supervisor must supply exclusive ownership of the runtime, artifact fingerprint validation and process-generation fencing.

## Failure and recovery

States: `unknown`, `unloaded`, `loading`, `ready`, `unloading`, `uncertain`.

Load response must be `text/event-stream`. The parser supports chunked CRLF/LF framing, comments, multiline data and auxiliary SSE metadata. It bounds event bytes, total bytes, event count and total operation duration. Every observed component must finish; a finished main-model event alone does not conceal a later warmup error. This is intentionally stricter than upstream's optional warmup behavior: upstream can skip a partially failed warmup and finish loading, whereas this adapter requires reconciliation after an incomplete observed warmup phase. HTTP 200 with an error object, malformed or truncated JSON/SSE, missing terminal state, disagreement between endpoints, or a lost admission generation cannot produce READY.

Cancellation, timeout or transport loss clears active readiness and enters UNCERTAIN. Because pinned Tabby continues a detached load after client disconnect, `apply()` and `unload()` refuse another transition in that state. `reconcile(pending_profile)` can restore READY only by observing the exact desired settings under exclusive ownership. If observation is absent, mismatched or unavailable, keep admission closed and have the resource coordinator settle/retire the owned runtime; then create a controller bound to the new verified process generation. Never turn a 503 into proof that an outstanding detached operation stopped. The library never kills a process or retries loading automatically.

One lock serializes transitions and entire generation leases. A caller must not recursively request a transition while holding its own generation lease. The authority owns deadlines/cancellation for generation code and lock holders; this package bounds engine control I/O, not arbitrary user code inside a lease. A canceled/interrupted generation marks the control state uncertain because upstream quiescence is not established.

## Verification

From this package directory, using the already configured development environment:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
$env:HERMES_TABBY_SOURCE = 'G:\Project_Ned\runtime\tabbyAPI' # Read-only pinned source characterization
python -m pytest -c pyproject.toml tests -q > "$env:TEMP\hermes-inference-tests.txt" 2>&1
Get-Content -LiteralPath "$env:TEMP\hermes-inference-tests.txt"
python -m ruff check src tests
python -m ruff format --check src tests
```

No package installation is needed for these checks: pytest uses `src` from its package-local configuration. Tests use random synthetic credentials and synthetic endpoint responses. They do not read server auth files, contact localhost, load models, run GPU telemetry, launch processes or change installed runtimes.

Live V3 certification, V2 pack selection, host-wide durable GPU leases, persistent Gaming policy, active-stream cancellation, artifact integrity, embeddings/conversion teardown and measured VRAM evacuation are separate integration gates. No V2 runtime is claimed by this package.

## Pinned source references

- [Load and observation routes](https://github.com/theroyallab/tabbyAPI/blob/2fd6cc76203a66e13042daf7d76e5898b21c1ad8/endpoints/core/router.py)
- [Load/response fields](https://github.com/theroyallab/tabbyAPI/blob/2fd6cc76203a66e13042daf7d76e5898b21c1ad8/endpoints/core/types/model.py)
- [Detached load and SSE errors](https://github.com/theroyallab/tabbyAPI/blob/2fd6cc76203a66e13042daf7d76e5898b21c1ad8/endpoints/core/utils/model.py)
- [Same-model shortcut and V2 rejection](https://github.com/theroyallab/tabbyAPI/blob/2fd6cc76203a66e13042daf7d76e5898b21c1ad8/common/model.py)
- [Effective model settings and cache aliases](https://github.com/theroyallab/tabbyAPI/blob/2fd6cc76203a66e13042daf7d76e5898b21c1ad8/backends/exllamav3/model.py)
