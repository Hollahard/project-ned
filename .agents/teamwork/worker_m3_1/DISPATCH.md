# Task Assignment — worker_m3_1

## Mission
Implement Milestone 3: Core Memory & Vector Database Foundation (Requirement R3).

## Context & Inputs
1. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (MANDATORY: read Section `## 2026-10-09T13:42:19Z` first!)
2. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\orchestrator_3\PROJECT.md`
3. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\GEMINI.md` (Strict workspace rules: always route test commands through temporary files `cmd.exe /c "..." > log.txt 2>&1`, inspect via `view_file`, and delete immediately).
4. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\docs\hermes-native-desktop\ARCHITECTURE.md` (Read Section 10: Vector Memory Specification).
5. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\docs\hermes-native-desktop\FEATURE-REVIEW.md` (Read F02: Canonical delete/rewind validity, and F03: Outbox and recovery reconciliation).
6. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\services\core\src\friday\memory\` (Existing memory modules: `coordinator.py`, `semantic.py`, `episodic.py`, `procedural.py`, `working.py`).
7. `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\services\core\src\friday\storage\db.py` (Existing `DatabaseManager`).

## Write Ownership
You have exclusive write ownership of:
- `services/core/src/friday/memory/vector.py` (new)
- `services/core/src/friday/memory/reconciliation.py` (new)
- `services/core/src/friday/memory/coordinator.py`
- `services/core/src/friday/memory/__init__.py`
- `services/core/src/friday/storage/vector_db.py` (new)
- `services/core/tests/test_memory_vector.py` (new)

DO NOT modify files outside your write ownership. Preexisting dirty files in `apps/desktop/` must NOT be touched.

## Objectives & Acceptance Criteria
1. **Durable Local Memory Schema**:
   - Implement profile-scoped SQLite vector memory storage supporting the logical schema:
     * `memory_sources` (`source_id`, `profile`, `kind`, `session_id`, `message_id`, `revision`, `canonical_locator`, `content_hash`, `retention_policy`, `deletion_generation`)
     * `memory_items` (`item_id`, `source_id`, `text`, `provenance_span`, `author_trust_label`, `valid_from`, `valid_to`, `tombstone`, `revision`)
     * `memory_chunks` (`chunk_id`, `item_id`, `ordinal`, `content_hash`, `extraction_version`, `token_count`)
     * `embedding_versions` (`version_id`, `model_id`, `dimension`, `metric`, `normalization`, `runtime_fingerprint`)
     * `chunk_vectors` (`chunk_id`, `embedding_version`, `index_generation`, `vector`)
     * `ingestion_outbox` (`event_id`, `source_id`, `revision`, `action`, `dedup_key`, `attempts`, `next_attempt`, `last_error`)
     * `retrieval_audit` (`audit_id`, `request_id`, `item_ids`, `scores`, `index_generation`, `created_at`)
     * `index_generations` (`generation_id`, `state`, `counts`, `checksum`, `source_high_watermark`, `schema_version`)
   - Support `sqlite-vec` / `vec0` virtual table if the extension is present, with an embedded deterministic vector search fallback (exact cosine similarity / dot product) so vector retrieval works 100% offline without external dependencies or cloud calls.
2. **Local CPU Embedding Pipeline**:
   - Provide an offline, deterministic CPU embedding engine (e.g. normalized vectors of fixed dimension, e.g. 128 or 384 dimensions) with zero external network or cloud API calls.
3. **F02 Canonical Delete/Rewind Validity Boundary**:
   - Implement immediate canonical delete/rewind invalidation at the retrieval boundary.
   - When vector search recalls candidates, verify their source validity against canonical state (`sessions`, `messages`, `semantic_memory`).
   - If a source message or session has been soft-deleted (`is_deleted=1`, `active=0`), rewound, or is absent: FAIL CLOSED. The recalled chunk must be excluded from search results immediately!
   - Ensure zero recall of tombstoned or rewound content.
4. **F03 Outbox & Recovery Reconciliation**:
   - Implement atomic write of source metadata + outbox event in `ingestion_outbox`.
   - Implement idempotent reconciliation: an ingestion cursor / high-watermark scanner that catches up unindexed canonical commits after restart or crash.
   - Fault-injection testing: simulate crash between canonical write and provider callback, verify reconciliation catches up without duplicate or lost memory chunks.
5. **Context Fencing**:
   - Ensure all retrieved memory excerpts are fenced with `MEMORY_OUTPUT_FENCE_PREFIX` (`[TOOL RESULT: MEMORY SEARCH DATA ONLY...]`) so they cannot act as instruction sources.
6. **Async Database Fixture Teardown**:
   - All async pytest fixtures must explicitly `await db_manager.close()` during teardown to avoid Windows SQLite worker thread hangs.
7. **Comprehensive Test Suite**:
   - Write comprehensive tests in `services/core/tests/test_memory_vector.py` covering:
     * Schema initialization and WAL mode.
     * Local CPU embedding generation.
     * Vector insertion, chunking, and similarity search (KNN).
     * Hybrid FTS + vector search coordination in `MemoryCoordinator`.
     * F02 canonical delete / rewind invalidation (verifying deleted/rewound items never appear in recall).
     * F03 outbox processing and idempotent crash recovery reconciliation.
     * Untrusted excerpt fencing.
     * Async connection cleanup with zero hanging threads.
   - Ensure all existing 185 tests in `services/core/tests/` continue to pass without regressions.

## Mandate
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Deliver your handoff report to: `c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m3_1\handoff.md`.

## 2026-10-09T15:14:12Z
You are the Worker for Milestone 3: Core Memory & Vector Database Foundation (Requirement R3).
Your working directory is: c:\Users\Ghols\.codex\worktrees\hermes-compat\Project_Ned\.agents\teamwork\worker_m3_1
Your parent is orchestrator_3 (Conversation ID: 635b9360-b27f-4ffc-82d0-46001e560e8d).
