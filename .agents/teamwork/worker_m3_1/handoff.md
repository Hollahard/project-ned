# Handoff Report: Milestone 3 — Core Memory & Vector Database Foundation (Requirement R3)

## 1. Observation
- **Direct Workspace Baseline Inspection**:
  * Prior to implementation, `services/core/tests/` had 185 test cases across 40 test files (`pytest --collect-only -q` returned `185 tests collected in 1.03s`).
  * `services/core/src/friday/memory/` previously contained 4 memory tiers: `working.py`, `episodic.py`, `semantic.py`, `procedural.py`, coordinated by `coordinator.py`.
  * `services/core/src/friday/storage/` contained `db.py` (`DatabaseManager` managing WAL SQLite storage for `sessions`, `messages`, `semantic_memory`, etc.).
  * No vector database manager, embedding pipeline, or outbox reconciliation engine existed.
  * Running `uv pip list` demonstrated that `sqlite-vec` C extension and `numpy` were not pre-installed in the Python 3.12 virtual environment (`ModuleNotFoundError: No module named 'sqlite_vec'`).

- **Implementation Execution**:
  * Created `services/core/src/friday/storage/vector_db.py` implementing `VectorDatabaseManager` with SQLite WAL mode, foreign keys, probe for `sqlite-vec` extension, pure-Python cosine similarity fallback with `pack_vector`/`unpack_vector`, FTS5 chunks index, and the 8 required tables: `memory_sources`, `memory_items`, `memory_chunks`, `embedding_versions`, `chunk_vectors`, `ingestion_outbox`, `retrieval_audit`, `index_generations`.
  * Created `services/core/src/friday/memory/vector.py` implementing:
    - `LocalCpuEmbedder`: 100% offline, deterministic CPU embedding engine (128-dimensional dense vector) using subword character n-grams and signed feature hash projection with L2 unit normalization, requiring zero network or cloud calls.
    - `VectorMemory`: Atomic outbox writes (`memory_sources` + `memory_items` + `ingestion_outbox`), chunking, KNN retrieval, `forget()`, `rewind_session()`, and F02 canonical validity enforcement (`_verify_canonical_validity`) failing closed at the retrieval boundary when canonical records (`sessions`, `messages`, `semantic_memory`) are absent or deleted.
    - Context fencing: `format_fenced_excerpts` prefixing outputs with `MEMORY_OUTPUT_FENCE_PREFIX`.
  * Created `services/core/src/friday/memory/reconciliation.py` implementing `ReconciliationEngine` with:
    - `reconcile_outbox`: Idempotent processing of pending/failed outbox events.
    - `reconcile_canonical`: High-watermark catchup scanner reconciling unindexed canonical commits (messages and semantic memories) and synchronizing deletions/tombstones.
  * Updated `services/core/src/friday/memory/coordinator.py`: Added optional `vector_db` / `vector_memory` parameters to `MemoryCoordinator` and integrated vector search into multi-tier query execution and context fencing.
  * Updated `services/core/src/friday/memory/__init__.py`: Exported all new vector memory classes, embedder, models, and reconciliation engine.
  * Created `services/core/tests/test_memory_vector.py`: 11 comprehensive tests exercising WAL schema initialization, embedder determinism/normalization/subword semantics, KNN search, F02 canonical delete invalidation, F02 canonical session deletion cascading, F02 canonical rewind invalidation, F03 outbox crash recovery, F03 canonical catchup scanner, hybrid coordinator search, and immediate tombstoning.

- **Verification Execution**:
  * Targeted test execution via:
    `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/test_memory_vector.py -v > test_vec_run.txt 2>&1"`
    Result: `11 passed in 0.33s`.
  * Full regression test execution across entire core test suite via:
    `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ > full_check.txt 2>&1"`
    Result: `196 passed in 18.49s` (185 baseline tests + 11 new tests = 196 passed, 0 failures, 0 errors).
  * Lint verification via:
    `cmd.exe /c ".\.venv\Scripts\ruff.exe check services/core/src/friday/memory/vector.py services/core/src/friday/memory/reconciliation.py services/core/src/friday/memory/coordinator.py services/core/src/friday/memory/__init__.py services/core/src/friday/storage/vector_db.py services/core/tests/test_memory_vector.py"`
    Result: `All checks passed!`.
  * Git status check via `git status --porcelain`: Confirmed that write ownership was strictly respected; only files within the assigned write ownership were touched.

## 2. Logic Chain
1. *Observation*: `sqlite-vec` and `numpy` are not present in `.venv`.
   *Inference*: The vector memory system must not crash or depend on external binary extensions.
   *Resolution*: Implemented dual-engine vector database: if `sqlite_vec` C extension is present, load `vec0`; otherwise, seamlessly utilize standard library `struct`, `math`, and SQLite blob storage with exact cosine similarity KNN calculation.
2. *Observation*: Requirement R3 / Objective 2 requires local CPU embeddings with zero external cloud dependencies.
   *Inference*: Embeddings must be generated offline, deterministically, and quickly without network I/O.
   *Resolution*: Built `LocalCpuEmbedder` using subword character n-grams and signed SHA-256 feature projection with L2 normalization, ensuring identical strings produce identical vectors, morphologically related words achieve high cosine similarity, and zero external APIs are invoked.
3. *Observation*: Requirement F02 specifies that provider callbacks alone cannot guarantee delete/rewind validity because direct DB deletions or rewind operations bypass vector providers.
   *Inference*: Vector candidate retrieval must resolve validity against the authoritative canonical database (`sessions`, `messages`, `semantic_memory`) at the retrieval boundary.
   *Resolution*: Implemented `_verify_canonical_validity` in `VectorMemory.search()`. When vector search recalls candidates, it queries the canonical database to verify that the message/session/semantic row exists and is not soft-deleted or rewound. If absent or invalid, it immediately drops the candidate (fail-closed).
4. *Observation*: Requirement F03 specifies that writes to canonical storage and vector plugins are not atomic across databases, meaning a crash between canonical write and vector ingestion leaves unindexed records.
   *Inference*: Storage must maintain a durable ingestion outbox and an idempotent high-watermark catchup scanner.
   *Resolution*: Implemented `ingestion_outbox` in `vector_db.py`, atomic ingestion transactions in `vector.py`, and `ReconciliationEngine` in `reconciliation.py`. The reconciler scans canonical tables against `memory_sources` by content hash, index unindexed items, and prune orphaned sources idempotently.
5. *Observation*: GEMINI.md mandates that all async database fixtures explicitly `await db_manager.close()` during teardown to prevent Windows SQLite worker thread hangs.
   *Resolution*: Configured `canonical_db` and `vector_db` pytest async fixtures in `test_memory_vector.py` with `try ... finally: await manager.close()`. All 196 tests complete and terminate cleanly in subshells with zero hanging processes.

## 3. Caveats
- `sqlite-vec`: While `vec0` virtual table creation and extension loading are fully implemented and probed in `VectorDatabaseManager.initialize()`, the default runtime environment operates on the pure-Python / SQLite fallback because the optional binary wheel is not installed in `.venv`. The pure-Python implementation is 100% functional and tested.
- No caveats regarding regressions: all 185 preexisting tests in `services/core/tests/` passed cleanly alongside the 11 new tests.

## 4. Conclusion
Milestone 3 (Core Memory & Vector Database Foundation, Requirement R3) is fully implemented, verified, and passing:
- Durable local SQLite WAL schema with 8 tables and FTS5 indexing.
- Local offline deterministic CPU embedding pipeline.
- F02 canonical delete/rewind immediate validity enforcement (fail-closed retrieval boundary).
- F03 outbox and recovery reconciliation engine with idempotent crash recovery.
- Context fencing with `MEMORY_OUTPUT_FENCE_PREFIX`.
- Strict async connection cleanup and zero hanging threads.
- 100% test pass rate (196/196) and 100% clean ruff linting.

## 5. Verification Method
To independently verify this milestone on Windows with pwsh:
1. Run targeted vector memory tests:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/test_memory_vector.py -v > log.txt 2>&1"
   ```
   Inspect `log.txt` (expect 11 passed in ~0.35s) and delete `log.txt`.
2. Run full core regression suite:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ > log.txt 2>&1"
   ```
   Inspect `log.txt` (expect 196 passed in ~19s) and delete `log.txt`.
3. Run linting check:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\ruff.exe check services/core/src/friday/memory/vector.py services/core/src/friday/memory/reconciliation.py services/core/src/friday/memory/coordinator.py services/core/src/friday/memory/__init__.py services/core/src/friday/storage/vector_db.py services/core/tests/test_memory_vector.py"
   ```
   (Expect `All checks passed!`).
