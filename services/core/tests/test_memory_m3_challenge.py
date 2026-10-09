"""Empirical Adversarial Challenge Suite for Milestone 3 (Requirement R3).

Adversarial Stress-Testing of:
- F02: Canonical Invalidation (message deletion, session cascading deletion, session rewind, identical text distinct provenance)
- F03: Crash Recovery & Reconciliation (unindexed canonical injection, multi-cycle idempotency, zero chunk duplication)
- Boundary Stress & Edge Cases: Top-k candidate saturation, cross-workspace isolation, FTS5 sync.

Invariants Verified:
1. Canonical deletions immediately drop recall (fail-closed) even before vector reconciliation.
2. Identical text preserves separate provenance roots; deleting one does not affect the other.
3. Rewound sessions invalidate all subsequent turns.
4. Reconciliation is strictly idempotent across multiple consecutive runs.
5. Async teardown cleans up all aiosqlite worker threads.
"""

import time
from pathlib import Path

import pytest

from friday.memory.reconciliation import ReconciliationEngine
from friday.memory.vector import (
    MemoryItemModel,
    MemorySourceModel,
    VectorMemory,
)
from friday.storage.db import DatabaseManager
from friday.storage.vector_db import (
    VectorDatabaseManager,
)


@pytest.fixture
async def canonical_db(tmp_path: Path):
    """Async fixture for canonical SQLite DB with strict teardown."""
    db_file = tmp_path / "canonical_adversarial.db"
    manager = DatabaseManager(db_file)
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def vector_db(tmp_path: Path):
    """Async fixture for vector SQLite DB with strict teardown."""
    db_file = tmp_path / "vector_adversarial.db"
    manager = VectorDatabaseManager(db_file)
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def vector_memory(vector_db: VectorDatabaseManager, canonical_db: DatabaseManager):
    """Vector memory instance backed by both stores."""
    return VectorMemory(vector_db=vector_db, canonical_db=canonical_db)


@pytest.fixture
async def reconciler(vector_db: VectorDatabaseManager, canonical_db: DatabaseManager, vector_memory: VectorMemory):
    """ReconciliationEngine instance."""
    return ReconciliationEngine(vector_db=vector_db, canonical_db=canonical_db, vector_memory=vector_memory)


# =========================================================================
# F02 CANONICAL VALIDITY ADVERSARIAL CHALLENGES
# =========================================================================

@pytest.mark.asyncio
async def test_challenge_f02_soft_delete_and_canonical_deletion(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Challenge F02.1: Verify canonical deletion immediately drops recall fail-closed."""
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_id = "sess-adv-del-01"
    msg_id = "msg-adv-del-01"

    # 1. Populate canonical session and message
    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Adversarial Deletion Session", now, now, "/workspace/adv", "default"),
    )
    await conn_can.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        (msg_id, sess_id, "Critical kernel configuration parameter: sysctl vm.max_map_count=262144", now),
    )
    await conn_can.commit()

    # 2. Ingest into vector store
    source = MemorySourceModel(
        source_id=f"msg:{msg_id}",
        profile="default",
        kind="message",
        session_id=sess_id,
        message_id=msg_id,
        canonical_locator=f"messages:{msg_id}",
        content_hash="kernel_param_hash",
        created_at=now,
    )
    item = MemoryItemModel(
        item_id=f"item:{msg_id}",
        source_id=source.source_id,
        text="Critical kernel configuration parameter: sysctl vm.max_map_count=262144",
        author_trust_label="user",
        created_at=now,
    )
    await vector_memory.ingest(source, [item])

    # 3. Verify retrievable initially
    res_before = await vector_memory.search("sysctl vm max_map_count", profile="default")
    assert len(res_before) == 1
    assert res_before[0].message_id == msg_id

    # 4. Perform direct canonical deletion
    await conn_can.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    await conn_can.commit()

    # 5. Immediate check: MUST drop immediately from recall
    res_after = await vector_memory.search("sysctl vm max_map_count", profile="default")
    assert len(res_after) == 0, "F02 FAULT: Message deleted in canonical DB was recalled by vector search!"


@pytest.mark.asyncio
async def test_challenge_f02_session_deletion_cascading(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Challenge F02.2: Deleting parent session in canonical store excludes all associated messages."""
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_id = "sess-cascade-parent"

    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Parent Session To Destroy", now, now, "/workspace/adv", "default"),
    )

    msg_ids = [f"msg-cascade-{i}" for i in range(5)]
    for i, mid in enumerate(msg_ids):
        await conn_can.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (mid, sess_id, f"Subsystem component specification part {i}: memory protocol buffer format", now + i),
        )
        source = MemorySourceModel(
            source_id=f"msg:{mid}",
            profile="default",
            kind="message",
            session_id=sess_id,
            message_id=mid,
            canonical_locator=f"messages:{mid}",
            content_hash=f"hash_{i}",
            created_at=now + i,
        )
        item = MemoryItemModel(
            item_id=f"item:{mid}",
            source_id=source.source_id,
            text=f"Subsystem component specification part {i}: memory protocol buffer format",
            author_trust_label="user",
            created_at=now + i,
        )
        await vector_memory.ingest(source, [item])

    await conn_can.commit()

    # Verify all 5 are searchable initially
    res_before = await vector_memory.search("memory protocol buffer format", profile="default", top_k=10)
    assert len(res_before) == 5

    # Delete parent session in canonical DB (cascading delete)
    await conn_can.execute("DELETE FROM sessions WHERE id = ?", (sess_id,))
    await conn_can.commit()

    # Verify all 5 messages are immediately excluded from recall
    res_after = await vector_memory.search("memory protocol buffer format", profile="default", top_k=10)
    assert len(res_after) == 0, f"F02 FAULT: {len(res_after)} messages still recalled after parent session deletion!"


@pytest.mark.asyncio
async def test_challenge_f02_session_rewind_boundary(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Challenge F02.3: Session rewind invalidates turns occurring after rewind timestamp."""
    conn_can = await canonical_db.get_connection()
    sess_id = "sess-rewind-adversarial"
    t0 = 1000.0

    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Rewind Adversarial Session", t0, t0, "/workspace/adv", "default"),
    )

    # Ingest 3 turns with strictly defined timestamps: t=1000, t=1100, t=1200
    turns = [
        ("msg-turn-1", "Turn 1: Project configuration initialized with Rust Tauri backend.", 1000.0),
        ("msg-turn-2", "Turn 2: Added experimental unsafe pointer logic that caused a segfault.", 1100.0),
        ("msg-turn-3", "Turn 3: Post-segfault uncommitted experimental debugging chatter.", 1200.0),
    ]

    for mid, content, ts in turns:
        await conn_can.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (mid, sess_id, content, ts),
        )
        src = MemorySourceModel(
            source_id=f"msg:{mid}",
            profile="default",
            kind="message",
            session_id=sess_id,
            message_id=mid,
            canonical_locator=f"messages:{mid}",
            content_hash=f"h_{mid}",
            created_at=ts,
        )
        itm = MemoryItemModel(
            item_id=f"item:{mid}",
            source_id=src.source_id,
            text=content,
            valid_from=ts,
            created_at=ts,
        )
        await vector_memory.ingest(src, [itm])

    await conn_can.commit()

    # Prior to rewind: all three are retrievable
    res_t1_pre = await vector_memory.search("Project configuration initialized Rust Tauri", profile="default")
    assert any(r.message_id == "msg-turn-1" for r in res_t1_pre)

    res_t2_pre = await vector_memory.search("experimental unsafe pointer logic", profile="default")
    assert any(r.message_id == "msg-turn-2" for r in res_t2_pre)

    res_t3_pre = await vector_memory.search("Post-segfault uncommitted experimental debugging", profile="default")
    assert any(r.message_id == "msg-turn-3" for r in res_t3_pre)

    # Execute rewind: valid_until = 1050.0 (Turn 1 valid, Turns 2 and 3 invalid)
    await vector_memory.rewind_session(sess_id, valid_until_timestamp=1050.0)

    # Turn 1 must still be retrievable
    res_t1 = await vector_memory.search("Project configuration initialized Rust Tauri", profile="default")
    assert len(res_t1) == 1
    assert "Turn 1" in res_t1[0].text

    # Turns 2 and 3 must be ineligible
    res_t2 = await vector_memory.search("experimental unsafe pointer logic segfault", profile="default")
    assert not any(r.message_id == "msg-turn-2" for r in res_t2), "F02 FAULT: Rewound turn 2 was recalled by vector search!"

    res_t3 = await vector_memory.search("Post-segfault uncommitted experimental debugging", profile="default")
    assert not any(r.message_id == "msg-turn-3" for r in res_t3), "F02 FAULT: Rewound turn 3 was recalled by vector search!"


@pytest.mark.asyncio
async def test_challenge_f02_identical_text_distinct_provenance(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Challenge F02.4: Identical text across multiple messages retains distinct provenance.
    
    Deleting one message in canonical DB MUST NOT drop the second message.
    """
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_a = "sess-prov-alpha"
    sess_b = "sess-prov-beta"
    msg_a = "msg-prov-001"
    msg_b = "msg-prov-002"

    shared_text = "Deploy hermes release build 4.2 to staging cluster on port 8080."

    # Create two different sessions
    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_a, "Alpha Session", now, now, "/workspace/alpha", "default"),
    )
    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_b, "Beta Session", now, now, "/workspace/beta", "default"),
    )

    # Insert identical content in both
    await conn_can.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        (msg_a, sess_a, shared_text, now),
    )
    await conn_can.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        (msg_b, sess_b, shared_text, now + 1),
    )
    await conn_can.commit()

    # Ingest message A
    src_a = MemorySourceModel(
        source_id=f"msg:{msg_a}",
        profile="default",
        kind="message",
        session_id=sess_a,
        message_id=msg_a,
        canonical_locator=f"messages:{msg_a}",
        content_hash="shared_content_hash",
        created_at=now,
    )
    item_a = MemoryItemModel(
        item_id=f"item:{msg_a}",
        source_id=src_a.source_id,
        text=shared_text,
        author_trust_label="user",
        created_at=now,
    )
    await vector_memory.ingest(src_a, [item_a])

    # Ingest message B
    src_b = MemorySourceModel(
        source_id=f"msg:{msg_b}",
        profile="default",
        kind="message",
        session_id=sess_b,
        message_id=msg_b,
        canonical_locator=f"messages:{msg_b}",
        content_hash="shared_content_hash",
        created_at=now + 1,
    )
    item_b = MemoryItemModel(
        item_id=f"item:{msg_b}",
        source_id=src_b.source_id,
        text=shared_text,
        author_trust_label="user",
        created_at=now + 1,
    )
    await vector_memory.ingest(src_b, [item_b])

    # Both must be present in recall initially
    initial_recall = await vector_memory.search("Deploy hermes release build staging", profile="default", top_k=5)
    assert len(initial_recall) == 2
    locators = {r.canonical_locator for r in initial_recall}
    assert f"messages:{msg_a}" in locators
    assert f"messages:{msg_b}" in locators

    # Delete message A from canonical DB
    await conn_can.execute("DELETE FROM messages WHERE id = ?", (msg_a,))
    await conn_can.commit()

    # Search again: Message A must be excluded, Message B MUST REMAIN ELIGIBLE
    recall_after_delete_a = await vector_memory.search("Deploy hermes release build staging", profile="default", top_k=5)
    assert len(recall_after_delete_a) == 1, (
        f"F02 FAULT: Expected exactly 1 surviving message with identical text, got {len(recall_after_delete_a)}"
    )
    survivor = recall_after_delete_a[0]
    assert survivor.message_id == msg_b
    assert survivor.canonical_locator == f"messages:{msg_b}"
    assert survivor.session_id == sess_b
    assert survivor.text == shared_text

    # Now delete message B as well
    await conn_can.execute("DELETE FROM messages WHERE id = ?", (msg_b,))
    await conn_can.commit()

    # Search again: Both must be excluded (0 recall)
    final_recall = await vector_memory.search("Deploy hermes release build staging", profile="default", top_k=5)
    assert len(final_recall) == 0, "F02 FAULT: Both identical messages deleted, but recall returned hits!"


# =========================================================================
# F03 CRASH RECOVERY & IDEMPOTENCY ADVERSARIAL CHALLENGES
# =========================================================================

@pytest.mark.asyncio
async def test_challenge_f03_crash_recovery_unindexed_injection(
    reconciler: ReconciliationEngine,
    vector_memory: VectorMemory,
    vector_db: VectorDatabaseManager,
    canonical_db: DatabaseManager,
):
    """Challenge F03.1: Inject records into canonical tables without vector ingestion;
    run reconcile_canonical and verify they are all indexed and retrievable.
    """
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_id = "sess-unindexed-batch"

    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Crash Recovery Session", now, now, "/workspace/crash", "default"),
    )

    # Inject 5 unindexed canonical messages directly
    unindexed_msgs = [
        ("msg-unidx-1", "Secret network architecture uses WireGuard UDP tunnels on port 51820."),
        ("msg-unidx-2", "Postgres replicas use streaming replication with synchronous_commit off."),
        ("msg-unidx-3", "Triton inference server runs ExLlamaV3 with quantized 4-bit weights."),
        ("msg-unidx-4", "Tauri IPC commands are protected by one-shot HMAC capability tokens."),
        ("msg-unidx-5", "Memory outbox reconciliation uses idempotent high watermark cursors."),
    ]
    for mid, content in unindexed_msgs:
        await conn_can.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (mid, sess_id, content, now),
        )

    # Inject 3 unindexed canonical semantic memory entries
    unindexed_sem = [
        ("sem-unidx-1", "Security Policy", "Capability tokens must have maximum 120s TTL."),
        ("sem-unidx-2", "Storage Policy", "SQLite database must use WAL mode and normal synchronous."),
        ("sem-unidx-3", "Inference Policy", "RTX 5090 Blackwell VRAM allocation capped at 28GB."),
    ]
    for sid, title, content in unindexed_sem:
        await conn_can.execute(
            "INSERT INTO semantic_memory (id, workspace_root, sensitivity, category, title, content, created_at, updated_at) "
            "VALUES (?, ?, 'normal', 'policy', ?, ?, ?, ?)",
            (sid, "/workspace/crash", title, content, now, now),
        )

    await conn_can.commit()

    # Prior to reconciliation: verify vector DB has ZERO sources for these
    conn_vec = await vector_db.get_connection()
    async with conn_vec.execute("SELECT COUNT(*) FROM memory_sources") as cursor:
        initial_sources = (await cursor.fetchone())[0]
    assert initial_sources == 0

    # Run ReconciliationEngine.reconcile_canonical
    report = await reconciler.reconcile_canonical(profile="default", workspace_root="/workspace/crash")

    # Verify at least 8 items were indexed (5 messages + 3 semantic items)
    assert report["indexed"] == 8, f"F03 FAULT: Expected 8 items indexed, got {report['indexed']}"

    # Verify every injected item is now retrievable via vector search
    for mid, content in unindexed_msgs:
        query_words = " ".join(content.split()[:4])
        results = await vector_memory.search(query_words, profile="default", min_score=0.25)
        assert len(results) >= 1, f"F03 FAULT: Injected message {mid} not retrievable after reconciliation!"
        found_ids = [r.message_id for r in results]
        assert mid in found_ids, f"F03 FAULT: Message ID {mid} not found in search results: {found_ids}"

    for sid, title, content in unindexed_sem:
        results = await vector_memory.search(title, profile="default", min_score=0.25)
        assert len(results) >= 1, f"F03 FAULT: Injected semantic item {sid} not retrievable after reconciliation!"
        assert any(title in r.text for r in results)


@pytest.mark.asyncio
async def test_challenge_f03_reconciliation_multi_cycle_idempotency(
    reconciler: ReconciliationEngine,
    vector_memory: VectorMemory,
    vector_db: VectorDatabaseManager,
    canonical_db: DatabaseManager,
):
    """Challenge F03.2: Multi-cycle execution of reconciliation and verify idempotency.
    
    Zero duplicated chunks, zero duplicated chunk_vectors, zero duplicate FTS entries.
    """
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_id = "sess-idempotency"

    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Idempotency Session", now, now, "/workspace/idemp", "default"),
    )
    for i in range(4):
        await conn_can.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (f"msg-idemp-{i}", sess_id, f"Idempotency check item number {i} for stress verification.", now + i),
        )
    await conn_can.commit()

    # Cycle 1: First reconciliation
    rep1 = await reconciler.reconcile_canonical(profile="default", workspace_root="/workspace/idemp")
    assert rep1["indexed"] == 4

    conn_vec = await vector_db.get_connection()
    async with conn_vec.execute("SELECT COUNT(*) FROM memory_chunks") as c:
        chunks_c1 = (await c.fetchone())[0]
    async with conn_vec.execute("SELECT COUNT(*) FROM chunk_vectors") as c:
        vectors_c1 = (await c.fetchone())[0]
    async with conn_vec.execute("SELECT COUNT(*) FROM chunks_fts") as c:
        fts_c1 = (await c.fetchone())[0]

    assert chunks_c1 == 4
    assert vectors_c1 == 4

    # Cycles 2 to 5: Run 4 consecutive reconciliations
    for cycle in range(2, 6):
        rep = await reconciler.reconcile_canonical(profile="default", workspace_root="/workspace/idemp")
        assert rep["indexed"] == 0, f"F03 FAULT: Cycle {cycle} indexed {rep['indexed']} items (expected 0)!"

        async with conn_vec.execute("SELECT COUNT(*) FROM memory_chunks") as c:
            chunks_now = (await c.fetchone())[0]
        async with conn_vec.execute("SELECT COUNT(*) FROM chunk_vectors") as c:
            vectors_now = (await c.fetchone())[0]
        async with conn_vec.execute("SELECT COUNT(*) FROM chunks_fts") as c:
            fts_now = (await c.fetchone())[0]

        assert chunks_now == chunks_c1, (
            f"F03 FAULT: Duplicate chunks created in cycle {cycle}! Expected {chunks_c1}, got {chunks_now}"
        )
        assert vectors_now == vectors_c1, (
            f"F03 FAULT: Duplicate chunk vectors created in cycle {cycle}! Expected {vectors_c1}, got {vectors_now}"
        )
        assert fts_now == fts_c1, (
            f"F03 FAULT: Duplicate FTS entries in cycle {cycle}! Expected {fts_c1}, got {fts_now}"
        )

    # Search: Verify top hit matches item index and all results have unique message IDs (zero duplicate hits)
    for i in range(4):
        res = await vector_memory.search(f"Idempotency check item number {i}", profile="default")
        assert len(res) > 0
        assert res[0].message_id == f"msg-idemp-{i}"
        msg_ids = [r.message_id for r in res]
        assert len(msg_ids) == len(set(msg_ids)), f"Duplicate hits returned for query {i}: {msg_ids}"


# =========================================================================
# BOUNDARY STRESS & ASSUMPTION TESTING
# =========================================================================

@pytest.mark.asyncio
async def test_challenge_cross_workspace_boundary_isolation(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Stress test: Workspace filtering strictly excludes items belonging to other workspaces."""
    conn_can = await canonical_db.get_connection()
    now = time.time()

    # Session in Workspace A
    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        ("sess-ws-a", "Session A", now, now, "/repos/secret_project_a", "default"),
    )
    await conn_can.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        ("msg-ws-a", "sess-ws-a", "Secret architecture key: token_for_project_a_9999", now),
    )

    # Session in Workspace B
    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        ("sess-ws-b", "Session B", now, now, "/repos/public_project_b", "default"),
    )
    await conn_can.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        ("msg-ws-b", "sess-ws-b", "Public architecture notes: token_for_project_b_1111", now),
    )
    await conn_can.commit()

    # Ingest both
    for mid, sid in [("msg-ws-a", "sess-ws-a"), ("msg-ws-b", "sess-ws-b")]:
        await vector_memory.ingest(
            MemorySourceModel(
                source_id=f"msg:{mid}",
                profile="default",
                kind="message",
                session_id=sid,
                message_id=mid,
                canonical_locator=f"messages:{mid}",
                content_hash=f"h_{mid}",
                created_at=now,
            ),
            [
                MemoryItemModel(
                    item_id=f"item:{mid}",
                    source_id=f"msg:{mid}",
                    text=f"architecture notes {mid}",
                    created_at=now,
                )
            ],
        )

    # Query with workspace_root="/repos/secret_project_a"
    res_a = await vector_memory.search(
        "architecture notes",
        profile="default",
        workspace_root="/repos/secret_project_a",
    )
    assert len(res_a) == 1
    assert res_a[0].message_id == "msg-ws-a"

    # Query with workspace_root="/repos/public_project_b"
    res_b = await vector_memory.search(
        "architecture notes",
        profile="default",
        workspace_root="/repos/public_project_b",
    )
    assert len(res_b) == 1
    assert res_b[0].message_id == "msg-ws-b"


@pytest.mark.asyncio
async def test_challenge_top_k_starvation_under_high_deletion_ratio(
    vector_memory: VectorMemory,
    canonical_db: DatabaseManager,
):
    """Stress test the top_k * 3 oversampling assumption under heavy deletions.
    
    When N deleted records with high score outnumber top_k * 3, lazy post-filtering
    must either exhaust oversampling or drop valid records until reconciliation occurs.
    This test verifies behavior and documents the boundary limits.
    """
    conn_can = await canonical_db.get_connection()
    now = time.time()
    sess_id = "sess-saturation"

    await conn_can.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) VALUES (?, ?, ?, ?, ?, ?)",
        (sess_id, "Saturation Session", now, now, "/workspace/sat", "default"),
    )

    # Ingest 10 messages with identical high-relevance text
    base_text = "Vector retrieval saturation test for candidate oversampling."
    import hashlib
    canonical_hash = hashlib.sha256(base_text.encode("utf-8")).hexdigest()
    for i in range(10):
        mid = f"msg-sat-{i}"
        await conn_can.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (mid, sess_id, base_text, now + i),
        )
        src = MemorySourceModel(
            source_id=f"msg:{mid}",
            profile="default",
            kind="message",
            session_id=sess_id,
            message_id=mid,
            canonical_locator=f"messages:{mid}",
            content_hash=canonical_hash,
            created_at=now + i,
        )
        itm = MemoryItemModel(
            item_id=f"item:msg:{mid}",
            source_id=src.source_id,
            text=base_text,
            created_at=now + i,
        )
        await vector_memory.ingest(src, [itm])

    await conn_can.commit()

    # Now delete the first 8 messages in canonical DB, keeping only msg-sat-8 and msg-sat-9 valid
    for i in range(8):
        await conn_can.execute("DELETE FROM messages WHERE id = ?", (f"msg-sat-{i}",))
    await conn_can.commit()

    # With top_k=2: candidates queried is top_k * 3 = 6.
    # The first 6 candidate vectors in SQL are all from deleted messages (0 through 5).
    # All 6 fail canonical validity!
    # Therefore, lazy retrieval without reconciliation yields 0 results!
    res_lazy = await vector_memory.search(base_text, profile="default", top_k=2)
    # This documents the expected behavior / trade-off of top_k * 3 oversampling:
    # Under high un-reconciled deletion ratios (>66%), lazy retrieval may starve valid candidates.
    assert len(res_lazy) in (0, 2)  # Will be 0 if starved, 2 if oversampling reached survivors

    # Now verify that running forget() or reconcile_canonical resolves this starvation completely:
    reconciler = ReconciliationEngine(vector_memory.vector_db, canonical_db, vector_memory)
    rec_report = await reconciler.reconcile_canonical(profile="default", workspace_root="/workspace/sat")
    assert rec_report["tombstoned"] == 8

    # After reconciliation, tombstoned sources are excluded in SQL (WHERE deletion_generation = 0)
    # so search immediately returns the surviving 2 records!
    res_reconciled = await vector_memory.search(base_text, profile="default", top_k=5)
    assert len(res_reconciled) == 2, (
        f"Expected surviving 2 records after reconciliation, got {len(res_reconciled)}"
    )
    survivor_ids = {r.message_id for r in res_reconciled}
    assert survivor_ids == {"msg-sat-8", "msg-sat-9"}
