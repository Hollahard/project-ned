# Model artifact inspection checkpoint — 2026-10-08

The [model catalog](../../hermes-native/services/model-catalog/README.md) now implements the bounded, read-only inspection portion of the [approved import transaction](ARCHITECTURE.md#82-sideloadimport-transaction). It reads configuration, index files, tensor headers and allowlisted tokenizer/template metadata from a host-granted local directory. It does not register or copy models, read tensor payloads, import model-supplied Python, start an engine, measure VRAM or certify loading.

## Implemented inspection

The public API is `inspect_model(granted_root, relative_model, limits=None) -> InspectionReport`. The root must be explicitly selected by the host; the model is one immediate child folder name. The standalone CLI accepts `--root` and `--model` and can run under Python `-I -S -B`, without site packages. It emits a bounded JSON object and static diagnostic codes. This introduces no renderer filesystem capability or model-selector UI.

Configuration, index and safetensors-header JSON rejects duplicate keys, nonfinite numbers, malformed UTF-8 and excessive depth/counts. Tensor dtype, shape and offsets are checked against each file's payload extent without reading that payload. Available shards must match their index mappings; duplicates, missing/unreferenced shards, inconsistent numbering, overlapping/holey ranges and size mismatches are explicit. Missing shards preserve valid observations from the remaining files.

The default bounds are 1 MiB config, 32 MiB index/header, 64 MiB per allowlisted auxiliary file, 256 MiB total reads including comparison passes, 64 shards, 500,000 retained observed tensors, and 128 KiB output. The global tensor cap is checked before growing the retained union and stops later shard reads. Output truncation preserves aggregate security/changed/invalid severity. Unsupported dtypes or inspection limits are distinguished from corruption.

Windows reads reject UNC/device/network roots, traversal, ADS, reserved names and all symlink/reparse components. Files use query/read-only handles with write/delete sharing denied while held, resolved-handle path checks, descriptor/path identity checks, repeated metadata/header digests and final directory/stat revalidation. Unicode, spaces and long absolute paths are tested. These checks are not an OS sandbox or an atomic directory snapshot; external artifacts can change after inspection and must be revalidated before later load/restore operations.

Format and architecture fields remain observations. EXL3/EXL2/GPTQ labels reflect declared quantization metadata and recognized suffix consistency, not certified layouts or engine support. Quantization bits are declared, not measured. Architecture recognition comes from a small inspected ExLlamaV3 source set. GGUF receives only a magic observation and an unsupported-to-this-inspector result, preserving its separate llama.cpp path. The [reference receipt](../../hermes-native/services/model-catalog/REFERENCE-SOURCES.json) identifies the source observations without executing runtime code.

Every report sets `runtime_compatible: null`, `load_certified: false`, `weights_content_hashed: false` and `weight_payload_bytes_read: 0`. `metadata_fingerprint` includes critical metadata, opaque auxiliary fingerprints, tensor headers and file sizes; it is explicitly not a full weight-content hash. A same-size payload-only mutation can leave it unchanged. Tokenizer/template/auxiliary JSON hashes are opaque fingerprints; they do not claim semantic validation or duplicate-key checks of those auxiliary contents.

## Observed user artifacts

The following folders were read under the user's granted model root on 8 October 2026. They were not copied or modified. The integrated worktree repeated all three read-only inspections with byte-for-byte identical result objects. The [run receipt](implementation-evidence/model-catalog-receipt-worktree.json) records elapsed times and report hashes; bounded [Mistral](implementation-evidence/model-catalog-mistral-worktree.json), [Qwen3](implementation-evidence/model-catalog-qwen3-worktree.json) and [Qwen3.5](implementation-evidence/model-catalog-qwen35-worktree.json) observations preserve metadata hashes without embedding local root paths or full tensor headers.

| Folder | Declared bits | Referenced shards | Observed/indexed tensors | Result |
|---|---:|---:|---:|---|
| Mistral-Small-3.1-24B-Instruct-2503-exl3 | 5 | 2 | 1,147 / 1,147 | Metadata/header inspection complete |
| Qwen3-30B-A3B-Instruct-2507 | 5 | 3 | 56,117 / 56,117 | Metadata/header inspection complete |
| Qwen3.5-35B-A3B-exl3-clean | 4.09 | 3; first missing | 71,776 / 124,579 | Incomplete; `model-00001-of-00003.safetensors` missing |

The physical metadata/header comparison reads were 65,363,706, 92,066,192 and 173,249,794 bytes respectively, all below the 256 MiB budget. Weight payload reads were zero. The first two `metadata_inspected` results do not certify inference, tokenization, chat templates, context lengths, VRAM requirements or Gaming Mode eligibility.

| Folder family | Metadata fingerprint SHA-256 |
|---|---|
| Mistral 24B | `45630d422a23cc024f047f976880e8bea71e26c4c6a8d29660abb7ce2625b24c` |
| Qwen3 30B | `fc8f174222c988d84300281b14893f37dce011cd90b9261c08e8a4aa05d04b11` |
| Qwen3.5 35B, partial | `1b8b08a48a44cee03cd6531f83f7001e3b44a10457d178f9eab9d6525d8181bf` |

## Verification

The catalog passed 57 synthetic tests, Ruff and formatting checks. Coverage includes junction/ADS/network-root denial, Unicode/long paths, strict critical JSON, malformed tensor offsets/shapes, duplicate/inconsistent/missing shards, unsupported dtypes, header-only read-spy/canary assertions, changed metadata/directory detection, finite global state and diagnostic truncation severity. The CLI also runs in a base interpreter with `-I -S -B`. An independent source review identified the global-cap and truncated-severity issues; both were corrected and covered by regressions.

From the repository root, after activating the project virtual environment:

```powershell
$catalog = Join-Path $PWD 'hermes-native/services/model-catalog'
$checks = Join-Path $PWD 'hermes-native/.checks'
New-Item -ItemType Directory -Path $checks -Force | Out-Null
$fresh = Join-Path $checks ('catalog-' + [Guid]::NewGuid().ToString('N'))
python -m pytest -c "$catalog/pyproject.toml" -o addopts= "$catalog/tests" --basetemp $fresh -q
python -m ruff check "$catalog/src" "$catalog/tests" "$catalog/inspect_model.py"
python -m ruff format --check "$catalog/src" "$catalog/tests" "$catalog/inspect_model.py"
```

The [foundation verifier](../../hermes-native/scripts/Verify-Foundation.ps1) adds `model-catalog-tests`, `model-catalog-lint` and `model-catalog-format` using a fresh test directory. These checks use synthetic artifacts only and do not select any real model root, engine or GPU operation. PowerShell syntax and those three targeted checks were validated in the separate integration stage. The integrated worktree then passed **42 foundation groups and 450 component tests**, including renderer build and bounded native fixtures. The [foundation receipt](implementation-evidence/model-catalog-foundation-worktree.json) and [source-only integration receipt](implementation-evidence/model-catalog-source-receipt.json) identify this milestone. The previously verified Rust-owned HTTP proof and full Tauri profile suite remain separate runners; they were not repeated for this standalone catalog slice.

## Future UI and runtime boundary

The existing [native profile milestone](NATIVE-PROFILES-CHECKPOINT.md) remains schema validation and saved settings. This catalog slice changes no control-worker protocol, Rust control-host allowlist or retained profile UI. A future read-only preflight must obtain an explicit host grant, run under bounded ownership/admission, expose a finite report DTO and present `incomplete`/`unsupported` distinctly. Neither a renderer-supplied absolute path nor a saved profile alone may grant filesystem access.

Metadata inspection must not turn the saved profile into a ready artifact. Runtime-pack qualification, full content hashing where needed, tokenizer/template compatibility, explicit owned load/unload and requested/effective/measured profile settings remain separate gates. EXL2 qualification, manual inference/quantization/context measurements, GPU evacuation, fallback and hibernation are not established here. The stopped hidden WebView screenshot experiment is also separate and provides no profile-form visual proof.
