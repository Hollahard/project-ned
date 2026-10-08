# Owned model catalog host

This Windows-only Rust service owns a fresh, one-shot CPU Python inspector for each explicitly requested model-folder inspection. It uses the pure [model catalog](../model-catalog/README.md) and existing [resource owner](../resource-host/README.md). It does not import a model engine, tokenizer library or model-supplied Python, load weights, allocate GPU memory, start a server, or change model files. Source classification and declared quantization bits are observations, not runtime capability measurements.

## Host configuration and public API

`CatalogState::from_optional_config()` reads only the host environment variable `HERMES_NATIVE_CATALOG_CONFIG`. Its absence returns a default unavailable state. `CatalogState::from_config(&Path)` accepts a bounded strict JSON launch receipt. The renderer cannot select an executable, source root, root grant, working directory or timeout.

The receipt requires exactly `schema_version:1`, `python:{path,sha256}`, `bootstrap:{path,sha256}`, `catalog_src`, `working_directory`, `root_grants`, `sources`, `work_timeout_ms`, and `cleanup_timeout_ms`. There are one to eight local root grants. The exact source map contains `__init__.py`, `catalog.py`, `common.py`, `paths.py`, and `tensors.py` under `catalog_src/hermes_model_catalog`. All keys are required; unknown fields, duplicate JSON keys, invalid hashes and redirected/network paths are rejected. The file is at most 64 KiB, executable 64 MiB, each source/bootstrap 1 MiB. Hashes are rechecked for every inspection. Source-only Python loading hashes and retains the actual bytes it compiles, ignoring `.pyc` and extension shadows.

`prepare_config.py --python <resolved-base-exe> --catalog-src <absolute-src> --working-directory <fresh-absolute-directory> --root-grant <absolute-parent> [--root-grant ...] --output <fresh-absolute-receipt>` prepares the receipt without launching. The working directory parent and receipt parent must exist; both outputs must be outside source/model roots. Ordinary local DOS spellings are required by the preparer to avoid mixed namespace containment ambiguity. Resolve a uv alias with `Path(sys._base_executable).resolve()` before passing it. The child directory stays empty. The default work budget is 30 seconds, cleanup 5 seconds; host receipt values may lower them to 50 ms.

`try_admit(model_path: &str) -> Result<CatalogPermit, CatalogError>` acquires the one-operation permit before a caller dispatches a blocking task. `CatalogPermit::inspect(self) -> Result<serde_json::Value, CatalogError>` executes the request. `retire(Duration) -> Result<Option<Cleanup>, CatalogError>` permanently fences the state. State is `Default + Clone`. All errors expose only static `code`, `message`, and `retired` fields. `CATALOG_BUSY` rejects concurrent work immediately. Transport/protocol failure retires that one-shot generation after verified cleanup; a later request may create a fresh generation unless the window owner has retired or cleanup was incomplete.

The requested absolute DOS model path must name an immediate child of a host grant. Its lexical parent is matched before any requested-leaf filesystem probe, then canonical identity and root-to-leaf no-reparse checks are applied. Traversal, ADS and device basenames are denied. The narrowly validated ordinary grant spelling passed to Python must resolve to the same canonical root; the shared resource launcher is unchanged. Names beginning with a dash use an unambiguous `--model=<name>` argument.

## Lifetime and protocol

The permit publishes an independently reachable `Arc<WorkerGroup>` before task dispatch. Close/navigation can fence the Job while an inspector is queued, validating sources, launching, or reading. No state mutex is held through launch or capture. The resource owner creates the suspended process, assigns it to its private Job, and resumes it with an exact inherited handle list. Stdin is immediately closed, and both output pipes drain under bounded frame/tail storage.

The child launch is base Python `-I -S -B -X utf8 bootstrap.py` with only explicit arguments and `SYSTEMROOT`/`WINDIR`; there is no ambient PATH, Python configuration, shell, network endpoint or engine dependency. The work deadline starts at admission, so time spent queued or validating consumes the same budget. Process and filesystem OS calls are synchronous bounded-work operations, not hard real-time cancellable calls.

Exactly one LF-terminated UTF-8 JSON report is permitted, at most 65536 bytes including LF. Output is accepted only after strict DTO validation, root exit 0, both actual EOFs, completed drainers, final parser/queue exhaustion and an empty Job. Extra complete/partial frames, malformed output, crashes, descendant-held writers and timeouts withhold success. Failure cleanup has a separate maximum 5 second budget. `Cleanup {verified,root_exit_code,stdout_eof,stderr_eof,job_empty}` is emitted only after observed process/pipe/Job proof; `None` represents a generation with no child published after completed/no launch, not fabricated success. An unresolved publication race returns `CATALOG_CLEANUP_INCOMPLETE`. A result arriving after retirement is suppressed.

Dropping a queued permit fences its group and releases admission. Tauri must additionally validate exact live window identity before admission, retire on navigation/destruction/app exit, and recheck liveness after awaiting the blocking task. This crate has no Tauri dependency or renderer command binding.

## Compact result

The exact schema 1 keys are `model` (basename), `status`, `format`, `declared_architectures`, `declared_bits`, `observed_shard_count`, `observed_tensor_count`, `index_tensor_count`, `missing_shards`, `metadata_fingerprint`, `fingerprint_partial`, `fingerprint_scope`, `issues`, `issues_truncated`, `bytes_read`, `runtime_compatible`, `load_certified`, `weights_content_hashed`, and `weight_payload_bytes_read`, plus `schema` itself. Nullable fields are required explicitly. No absolute roots, raw config/header contents, stderr or arbitrary exception messages appear.

All missing names (up to 64) are retained. Issue detail is limited to 32 records and trimmed further only if required to fit the frame; `issues_truncated` is then true. Primary facts never disappear silently. UTF-8 encoding avoids ASCII escape inflation; mandatory facts exceeding the cap fail explicitly. Status comes from the full inspector report and is not downgraded when detail is trimmed. Recognized formats include EXL3/EXL2/GPTQ and truthful unsupported/unknown classifications. `runtime_compatible` remains null, `load_certified` and `weights_content_hashed` remain false, and `weight_payload_bytes_read` remains 0.

The fingerprint covers metadata files, auxiliary bytes, weight headers and file sizes. It does not hash large tensor payloads; changing payload bytes without changing sizes/headers may leave it unchanged. External model references can change after inspection. These launch receipts are source-integrity checks, not an OS sandbox, an atomic multi-file snapshot, complete Python DLL/stdlib attestation, or certification that a runtime can load the artifact. The future runtime pack must requalify and revalidate before a separate load operation.

## Verification

Run from an activated project environment with a fresh task-owned output directory:

```powershell
$env:HERMES_CATALOG_PYTHON = python -c 'from pathlib import Path; import sys; print(Path(sys._base_executable).resolve())'
$env:HERMES_CATALOG_TEST_ROOT = '<absolute-owned-test-output>'
$env:CARGO_TARGET_DIR = '<absolute-owned-build-output>'
cargo test --manifest-path services/catalog-host/Cargo.toml --locked --offline --quiet -- --test-threads=1
cargo clippy --manifest-path services/catalog-host/Cargo.toml --locked --offline --all-targets --quiet -- -D warnings
cargo fmt --manifest-path services/catalog-host/Cargo.toml -- --check
python -m pytest services/catalog-host/tests/test_bootstrap.py --basetemp '<fresh-owned-pytest-directory>' -q
python -m ruff check services/catalog-host/bootstrap.py services/catalog-host/prepare_config.py services/catalog-host/tests/test_bootstrap.py
python -m ruff format --check services/catalog-host/bootstrap.py services/catalog-host/prepare_config.py services/catalog-host/tests/test_bootstrap.py
```

The 17 Rust tests exercise required nullable DTO fields, strict frames, source mutation, outside grants, normal metadata changes, incomplete shards, queued/running/pre-publication retirement, cancelled admission, delayed duplicate/partial tails, malformed/oversized/early-exit peers, descendant-held EOF and unrelated process survival. The 6 Python tests cover bounded Unicode projection, source-only byte pinning/cache shadows, preparer no-write containment/namespace rejection, and the real bootstrap under engine/network/subprocess audit tripwires. All use synthetic tiny model headers. The full model-catalog parser suite remains separate.


The opt-in `examples/inspect.rs` diagnostic accepts only explicit `--config <receipt> --model <absolute-folder>` arguments. It runs the same admission/inspection/retirement path and emits a bounded JSON `{result,error,cleanup}` envelope, at most 66 KiB. Exit 0 requires both a valid inspection report (including truthful incomplete/unsupported reports) and verified process/pipe/Job cleanup. Exit 2 is a static host/protocol/cleanup failure. It neither creates grants nor loads a model:

```powershell
cargo run --manifest-path services/catalog-host/Cargo.toml --locked --offline --quiet --example inspect -- --config '<receipt>' --model '<granted-immediate-child>'
```
