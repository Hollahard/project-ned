# Model artifact metadata inspection

This pure-stdlib component implements the read-only portion of the approved architecture's §8.2 import transaction. It inspects a host-granted local model directory without importing an engine/tokenizer library, executing model Python, loading tensors, using a GPU, copying weights or writing into the model directory. It is not a registry, model profiler, runtime qualifier or load-admission decision.

```python
from pathlib import Path
from hermes_model_catalog import inspect_model

report = inspect_model(Path(r"C:\PyDev\LLM_PC\models"), "chosen-model-folder")
data = report.as_dict()
```

The root is selected by the host, never implicitly discovered from model metadata. The model argument is one immediate folder name. The separate [catalog host](../catalog-host/README.md) enforces native receipt grants and owns the inspector process. A native picker remains future work; this library does not create a renderer capability or expose arbitrary filesystem access.

The standalone CLI supports an isolated, no-site interpreter:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
python -I -S -B ./inspect_model.py --root 'C:\PyDev\LLM_PC\models' --model 'chosen-model-folder'
```

It emits one bounded JSON object. Exit zero means `metadata_inspected`; exit two means a partial, unsupported or rejected inspection. Neither exit code certifies loading. Diagnostics contain static codes and bounded filenames, not config contents, tokenizer text, templates, URLs or exception messages.

## Contract and limits

| Input/operation | Bound and behavior |
|---|---|
| Filesystem | Existing local fixed/removable drive; UNC/device/network roots, parent traversal, ADS, device names and all symlink/reparse components rejected |
| Directory | One level; at most 512 entries, 64 weight shards, 240-character safe basenames; Unicode, spaces and long absolute paths supported within Windows bounds |
| Critical JSON | Config 1 MiB; index/header 32 MiB each; duplicate keys, nonfinite numbers and malformed UTF-8 rejected; depth 64, nodes 4 million |
| Tensors | At most 500,000 across retained observed shards; limit checked before union growth and stops later shard reads; rank above 32 and unknown dtypes are unsupported rather than declared corrupt |
| Auxiliary files | Allowlisted tokenizer/template/processor/quantization files streamed in 64 KiB chunks, at most 64 MiB each; opaque fingerprints only, not JSON/tokenizer/template validation |
| Total reads | 256 MiB including repeated comparison reads; no safetensors payload reads |
| Output | At most 128 diagnostic items and 128 KiB JSON; truncation preserves aggregate security/changed/invalid severity |

Limits can be reduced using `Limits`; callers cannot raise the hard maxima. A cap is reported with a specific unsupported code, not interpreted as source corruption. There is no wall-clock guarantee for filesystem/kernel calls; large metadata is finite work and should run outside the UI thread under an outer managed deadline.

Critical files are opened read-only. On Windows the handle denies write/delete sharing while held, rejects a final reparse point, verifies its resolved name, and compares path/descriptor identity, size and modification time. Each critical metadata/header digest and each auxiliary file digest is read twice; final path stats and directory entries are checked again. CPython 3.12 Windows path-stat and descriptor-fstat expose different ctime semantics, so ctime is deliberately excluded from that cross-check. This is not an OS sandbox or atomic multi-file snapshot: externally referenced files can change after inspection, and hostile concurrent filesystem changes cannot be fully ruled out. Revalidate before future load/restore and use a separate full-content hashing/copy transaction when stronger integrity is required.

## Structural checks and truthful classification

Safetensors reads consist of its eight-byte header length and bounded JSON header. Known dtype/shape byte counts must match offsets. Offsets must fit the actual file payload extent, cover it exactly and contain no overlaps or holes; scalars and zero-length tensors are supported. `__metadata__` must be a string map. The index's tensor-to-shard map is checked against every available header, including duplicates across shards, missing/unreferenced files, standard shard numbering and declared total payload size. A missing shard preserves all safely inspected existing metadata and an explicit `missing_shards` list.

The format labels `EXL3`, `EXL2` and `GPTQ` reflect declared config metadata, checked for contradictory recognized tensor suffix markers. They do not certify those quantization layouts or runtime support. Undeclared HF weights remain `hf_unquantized_or_unspecified`; recognized packed suffixes without declarations remain `unknown`. GGUF receives only a four-byte magic observation and `GGUF_unsupported`, preserving its separate llama.cpp path. Quantization bit values are declared, not measured.

Architecture recognition is a small observed string set from the installed ExLlamaV3 source, not a capability matrix. Unknown strings return an unsupported reference-classification result. Model-supplied `auto_map` declarations are never executed. No EXL2/GPTQ runtime has been qualified by this component.

Every DTO includes `runtime_compatible: null`, `load_certified: false`, `weights_content_hashed: false`, and `weight_payload_bytes_read: 0`. `metadata_fingerprint` combines complete critical metadata hashes, optional opaque auxiliary hashes, weight-header hashes and file sizes. It excludes model-root location and timestamps. **Changing weight payload bytes without changing headers or sizes can leave this fingerprint unchanged**; a regression test demonstrates this limitation. Partial results have `fingerprint_partial: true`. No `ready` state is emitted.

The parsing reference is the [safetensors format specification](https://github.com/safetensors/safetensors#format). Local source observations are recorded in [REFERENCE-SOURCES.json](REFERENCE-SOURCES.json): Tabby commit `2fd6cc76203a66e13042daf7d76e5898b21c1ad8`, installed ExLlamaV3 package `1.5.4+cu132.torch2.11.0`, architecture declarations, config and quantization-export source. These files were read, not imported. The existing `LoadProfile` remains unchanged; this inspector neither creates default tuning values nor certifies saved profiles.

## Verification and observed models

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
New-Item -ItemType Directory .checks -Force | Out-Null
python -m pytest -q --tb=short --basetemp=.checks/new-test-run
python -m ruff check src tests inspect_model.py
python -m ruff format --check src tests inspect_model.py
```

The 57-test suite includes traversal/junction/ADS/network-root rejection, Unicode/long paths, strict JSON, tensor offset/shape/dtype cases, partial and inconsistent shard maps, finite global limits, mutation detection, aggregate diagnostic severity, opaque auxiliary treatment, and isolated CLI execution. A read-spy with a weight-payload canary verifies actual reads stop at the header boundary rather than trusting the DTO counter.

Read-only observations on 8 October 2026 under the user-granted `C:\PyDev\LLM_PC\models`:

| Folder | Declared format/bits | Header result |
|---|---|---|
| Mistral-Small-3.1-24B-Instruct-2503-exl3 | EXL3 / 5 | 1,147 tensor entries, two complete referenced shards |
| Qwen3-30B-A3B-Instruct-2507 | EXL3 / 5 | 56,117 tensor entries, three complete referenced shards |
| Qwen3.5-35B-A3B-exl3-clean | EXL3 / 4.09 | Incomplete: shard `model-00001-of-00003.safetensors` missing; 71,776 existing entries inspected of 124,579 indexed |

These observations are metadata/header checks only, with zero load certification. Actual bounded reports remain in the isolated stage's `reports` directory; user model files were not copied or modified. The original library slice changed no worker/UI interface. The later [native catalog integration](../../../docs/hermes-native-desktop/NATIVE-CATALOG-CHECKPOINT.md) adds a separate owned inspector and read-only profile-form action; runtime control remains separate.
