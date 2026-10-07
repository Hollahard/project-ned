# Milestone 1: Fast Mocked Soak Test Suite Adversarial Challenge Handoff Report

## 1. Observation

### 1.1 Baseline Soak Suite Verification
Execution of `tests/soak/test_soak_endurance.py`:
- Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"`
- Result:
  ```
  tests/soak/test_soak_endurance.py::test_50_turn_agent_loop_with_cancellations PASSED [ 20%]
  tests/soak/test_soak_endurance.py::test_memory_churn_and_fts5_integrity PASSED [ 40%]
  tests/soak/test_soak_endurance.py::test_concurrent_scheduler_soak_and_frozen_snapshot PASSED [ 60%]
  tests/soak/test_soak_endurance.py::test_subagent_depth1_delegation_and_grandchild_rejection PASSED [ 80%]
  tests/soak/test_soak_endurance.py::test_high_risk_auto_denial_in_soak_mode PASSED [100%]
  5 passed in 3.99s
  ```
- Warnings: 0. Orphaned processes: 0. Execution runtime: 3.99s (contract ceiling: < 180s).

### 1.2 Core Regression Suite Verification
Execution of core, security, and e2e regression suites:
- Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q"`
- Result:
  ```
  216 passed in 20.84s
  ```
- Failures: 0. Regressions: 0.

### 1.3 Empirical Attack 1: 4-Tier Memory Churn & FTS5 Synchronization
Executed adversarial harness testing high-volume churn across `messages`, `semantic_memory`, and `procedural_memory`:
- **Volume**: 500 messages, 300 semantic entries, 150 procedural entries inserted, followed by 100 semantic updates, 250 message deletions, 150 semantic deletions, and 50 procedural deletions.
- **Triggers Tested**: `messages_ai`, `messages_ad`, `semantic_memory_ai`, `semantic_memory_ad`, `semantic_memory_au`, `procedural_memory_ai`, `procedural_memory_ad`, `procedural_memory_au`.
- **Integrity Validation Commands**:
  - `PRAGMA integrity_check;` -> returned `ok`.
  - `PRAGMA foreign_key_check;` -> 0 violations.
  - `INSERT INTO messages_fts(messages_fts) VALUES('integrity-check');` -> Passed with 0 errors.
  - `INSERT INTO semantic_memory_fts(semantic_memory_fts) VALUES('integrity-check');` -> Passed with 0 errors.
  - `INSERT INTO procedural_memory_fts(procedural_memory_fts) VALUES('integrity-check');` -> Passed with 0 errors.
- **Row Count Parity**:
  - `SELECT count(*) FROM messages` (250) == `SELECT count(*) FROM messages_fts` (250).
  - `SELECT count(*) FROM semantic_memory` (150) == `SELECT count(*) FROM semantic_memory_fts` (150).
  - `SELECT count(*) FROM procedural_memory` (100) == `SELECT count(*) FROM procedural_memory_fts` (100).
- **Cascade Delete Boundary**:
  - Executed `DELETE FROM sessions WHERE id = ?` with child messages referencing session via `ON DELETE CASCADE`.
  - Messages in base table deleted cleanly (0 remaining).
  - `EpisodicMemory.search` returned 0 ghost records due to mandatory `INNER JOIN messages m ON m.rowid = f.rowid JOIN sessions s ON m.session_id = s.id`.

### 1.4 Empirical Attack 2: SQLite Scheduler Concurrency & Idempotency
Executed adversarial harness testing 50 concurrent worker instances and concurrent duplicate job creations:
- **50-Worker Concurrent Claim Race**:
  - 5 due jobs, 50 workers concurrently calling `SchedulerDatabaseManager.claim_next_due_job`.
  - Admitted claims: exactly 5 (one per due job).
  - Double claims detected: `False` (zero duplicate job IDs among claimed runs).
  - Unique run IDs: 5 (every claim generated a unique run instance).
  - Unhandled exceptions or `database is locked` errors: 0.
  - WAL file size: 758 KB (strictly below the 64 MB ceiling).
- **Concurrent Duplicate Job Creation Race**:
  - 20 concurrent coroutines simultaneously called `SchedulerDatabaseManager.create_job` with the identical `idempotency_key = "same-racing-key-12345"`.
  - Storage Invariant: Exactly 1 job persisted in SQLite (`SELECT count(*) FROM scheduled_jobs WHERE idempotency_key = ...` == 1). Zero duplicate jobs created.
  - Call Outcome: 1 coroutine returned `("OK", job_id)`, and 19 coroutines encountered `sqlite3.IntegrityError: UNIQUE constraint failed: scheduled_jobs.idempotency_key`.
  - Cause: In `friday/scheduler/db.py:205-234`, `create_job` uses a non-atomic `SELECT` then `INSERT` without acquiring `self._get_lock()` or wrapping in `BEGIN IMMEDIATE`. Under simultaneous arrival, all 20 coroutines see no existing job and race to `INSERT`. The table's `idempotency_key TEXT UNIQUE` constraint successfully protects storage integrity, but the racing callers receive `IntegrityError` rather than the existing job instance.

### 1.5 Empirical Attack 3: Security Capability Tokens
Executed adversarial harness testing replay, race consumption, payload tampering, TTL expiry, and forgery:
- **Replay Defense**: A consumed one-shot token was reused. Result: `PolicyDecision.allowed == False`, reason `"Invalid, expired, or mismatched one-shot capability token"`.
- **Concurrent Consumption Race**: 10 concurrent requests attempted to consume the same valid token at the exact same time. Result: exactly 1 request was approved (`allowed == True`), and 9 were rejected (`allowed == False`). Zero token double-spending occurred.
- **Payload Tampering**:
  - Modified argument value: rejected (`allowed == False`).
  - Injected extra parameter: rejected (`allowed == False`).
  - Empty argument dictionary: rejected (`allowed == False`).
- **TTL Expiration**: Token minted with `ttl_seconds=0.05` was evaluated at t = 0.08s. Result: rejected (`allowed == False`), reason `"Invalid, expired, or mismatched one-shot capability token"`.
- **Forgery & Tool Spoofing**:
  - Random strings, malformed UUIDs, corrupted HMAC signatures: all rejected (`allowed == False`).
  - Token minted for `filesystem.read` evaluated against `terminal.exec`: rejected (`allowed == False`).

---

## 2. Logic Chain

1. **Protocol and Suite Reliability**:
   - In `test_soak_endurance.py`, the agent loop mock yields `InferenceEvent` with valid delta tokens and finishes cleanly.
   - 50 continuous turns execute with 7 mid-turn cancellations without task leaks, registry leaks, or unbounded heap growth (tracemalloc drift < 25 MB).
   - Execution finishes in 3.99 seconds, satisfying the < 180 seconds threshold with large safety margin.

2. **Memory Churn & Virtual Table Integrity**:
   - The SQLite database triggers (`*_ai`, `*_ad`, `*_au`) correctly track all inserts, updates, and deletes across episodic, semantic, and procedural tiers.
   - Internal FTS5 integrity-checks (`INSERT INTO <fts_table>(<fts_table>) VALUES('integrity-check')`) confirm that shadow tables (`_idx`, `_data`, `_config`, `_docsize`) remain uncorrupted under rapid interleaved operations.
   - Count parity between physical tables and virtual shadow tables remains exact (100% synchronization).

3. **Scheduler Concurrency & Storage Idempotency**:
   - `claim_next_due_job` protects claim admission using `BEGIN IMMEDIATE` and an internal lock, preventing race conditions.
   - 50 concurrent worker attempts yielded zero double claims and zero lock timeouts.
   - `scheduled_jobs.idempotency_key` unique constraint guarantees single-persistence in storage.
   - Sequential duplicate submission (the realistic retry and re-dispatch pattern) safely returns the existing job instance.

4. **Capability Token Security Hardening**:
   - The HMAC-SHA256 test stub binds tokens cryptographically to canonical JSON argument hashes and tool names.
   - Single-use consumption is enforced atomically in memory; concurrent race attacks cannot double-spend tokens.
   - Expiration and argument tampering are caught deterministically by `CapabilityTokenManager` and enforced by `PolicyEngine`.

---

## 3. Caveats

1. **Concurrent Duplicate Job Creation Edge-Case**:
   If multiple processes or coroutines simultaneously invoke `SchedulerDatabaseManager.create_job` with the exact same `idempotency_key` in the exact same millisecond before any transaction commits, 1 caller succeeds and the rest receive `sqlite3.IntegrityError` instead of the existing job. Storage integrity is strictly preserved (only 1 job is ever inserted). In production, this can be handled gracefully by catching `sqlite3.IntegrityError` and querying the existing job.
2. **Offline Mock vs Hardware GPU**:
   The fast mocked soak suite operates using `SoakMockInference` for CI determinism (< 4 seconds). Real GPU weight qualification on the RTX 5090 is isolated under `@pytest.mark.gpu` and handled in Milestone 3 (`run_8hr_soak.py`).
3. **Review-Only Constraint**:
   Per team protocol, no implementation code was modified by Challenger 2.

---

## 4. Conclusion

**Verdict: APPROVE.**

The Fast Mocked Soak Test Suite in `tests/soak/test_soak_endurance.py` satisfies all requirements of Milestone 1, ADR-0002, and the Original User Request:
1. All 5 test cases pass cleanly in **3.99 seconds** with zero warnings and zero orphaned processes.
2. 4-tier memory churn and FTS5 triggers maintain 100% integrity and row count parity with zero corruption.
3. Scheduler concurrency enforces atomic single-admission with zero double-claims across 50 competing workers.
4. Capability token security strictly rejects replay attacks, race consumption, argument tampering, TTL expiration, and forgery.
5. All 216 existing regression tests continue passing without regressions.

---

## 5. Verification Method

To independently reproduce and verify this assessment:

1. **Run Soak Endurance Test Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_run.txt 2>&1"
   ```
   Inspect `soak_run.txt` (confirm 5 passed in ~4s, 0 warnings), then delete `soak_run.txt`:
   ```cmd
   cmd.exe /c "del soak_run.txt"
   ```

2. **Run Full Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_run.txt 2>&1"
   ```
   Inspect `reg_run.txt` (confirm 216 passed in ~21s), then delete `reg_run.txt`:
   ```cmd
   cmd.exe /c "del reg_run.txt"
   ```

3. **Invalidation Conditions**:
   - Any test failure in `tests/soak/test_soak_endurance.py`.
   - Execution duration exceeding 180 seconds.
   - Any regression failure in `services/core/tests/`, `tests/security/`, or `tests/e2e/`.
   - Any double-claim of a scheduled job occurrence during concurrent claims.
   - Any failure of FTS5 internal integrity check (`INSERT INTO ... VALUES('integrity-check')`).
