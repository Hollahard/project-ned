"""Empirical Challenger 2 Stress Suite for Milestone 3 (Vector Math, Embedder Invariants & Async DB Teardown).

Verifies:
1. Embedder bit-identical determinism across diverse multilingual, code, boundary, and extreme inputs.
2. Embedder unit normalization (L2 norm == 1.0 within 1e-6; zero vector on empty/whitespace).
3. Exact dimension consistency (128-D).
4. Semantic alignment: positive pairs vs distractor negatives with robust separation margins.
5. Strict zero-network invariant: zero socket connections or DNS lookups during embedding generation.
6. Multi-connection SQLite WAL concurrency and clean async teardown.
"""

import asyncio
import hashlib
import math
import random
import socket
import sys
from pathlib import Path

import pytest

from friday.memory.vector import (
    LocalCpuEmbedder,
    MemoryItemModel,
    MemorySourceModel,
    VectorMemory,
)
from friday.storage.vector_db import (
    DEFAULT_DIMENSION,
    VectorDatabaseManager,
    cosine_similarity,
    pack_vector,
)


def test_stress_embedder_determinism_and_bit_identical():
    """Verify identical text produces 100% bit-identical vectors across multiple runs and instances."""
    embedder = LocalCpuEmbedder(dimension=DEFAULT_DIMENSION)

    test_corpus = [
        "",
        " ",
        "   \t\n\r  ",
        "a",
        "Z",
        "!",
        "123",
        "The quick brown fox jumps over the lazy dog.",
        "SQLite WAL mode supports concurrent readers without blocking writers.",
        "High-performance local vector database running on Windows Job Objects with zero external cloud dependencies.",
        "Subword character n-grams ensure morphological invariance across conjugated verbs and plural forms.",
        "def cosine_similarity(v1: list[float], v2: list[float]) -> float: return dot / (norm1 * norm2)",
        "SELECT cv.chunk_id, cv.vector, mc.text FROM chunk_vectors cv JOIN memory_chunks mc ON cv.chunk_id = mc.chunk_id;",
        "use std::os::windows::io::AsRawHandle; struct JobObjectGuard { handle: HANDLE }",
        "Bonjour le monde, ceci est un test d'intégration vectorielle locale.",
        "Dies ist ein lokaler Vektoreinbettungstest für das Projekt Friday.",
        "这是一个用于本地向量嵌入的压力测试用例，完全离线运行。",
        "これはローカルベクトル埋め込みのテストケースです。ネットワーク接続はありません。",
        "Это локальный тест векторного хранилища без внешних сетевых вызовов.",
        "اختبار تضمين المتجهات المحلية لنظام التشغيل ويندوز بدون اتصال بالإنترنت.",
        "🚀🤖🔥 Modern AI system with deterministic offline vector retrieval 💻⚡",
        "sqlite " * 50,
        "a " * 200,
        "test " * 500,
        "long_test_string_" * 1000,
    ]

    rng = random.Random(42)
    for _ in range(50):
        length = rng.randint(5, 120)
        chars = [chr(rng.randint(32, 126)) for _ in range(length)]
        test_corpus.append("".join(chars))

    for idx, text in enumerate(test_corpus):
        v1 = embedder.embed(text)
        b1 = pack_vector(v1)

        for _ in range(3):
            fresh_embedder = LocalCpuEmbedder(dimension=DEFAULT_DIMENSION)
            v2 = fresh_embedder.embed(text)
            b2 = pack_vector(v2)

            assert b1 == b2, f"Bit-identical mismatch on input index {idx}"
            assert v1 == v2, f"Float mismatch on input index {idx}"


def test_stress_embedder_dimensions_and_unit_normalization():
    """Verify Euclidean norm equals 1.0 within 1e-6 for valid text, and zero vector on empty inputs."""
    embedder = LocalCpuEmbedder(dimension=DEFAULT_DIMENSION)

    samples = [
        "Normal english sentence with diverse vocabulary.",
        "Special chars !@#$%^&*()_+~`|}{[]:;?><,./",
        "Multi-line\nwith\r\ntabs\tand\fwhitespace",
        "Emoji test 🌟✨🎯🔥",
        "Code snippet: let mut x = Vec::new(); x.push(42);",
        "Very long input " * 200,
    ]

    for text in samples:
        vec = embedder.embed(text)
        assert len(vec) == DEFAULT_DIMENSION

        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6, f"Norm {norm} violates unit length for '{text[:20]}'"

        for val in vec:
            assert not math.isnan(val) and not math.isinf(val)

    # Empty and pure whitespace produce zero vectors without exception
    empty_samples = ["", "   ", "\n\t\r", "   \n   "]
    for empty_text in empty_samples:
        vec = embedder.embed(empty_text)
        assert len(vec) == DEFAULT_DIMENSION
        assert sum(vec) == 0.0
        assert all(x == 0.0 for x in vec)


def test_stress_embedder_semantic_alignment_and_margins():
    """Verify semantically/morphologically related strings yield significantly higher similarity than unrelated noise."""
    embedder = LocalCpuEmbedder(dimension=DEFAULT_DIMENSION)

    triads = [
        (
            "SQLite database WAL transaction journal",
            "SQLite WAL mode transaction logging and concurrency",
            "Chocolate cake recipe with melted butter and sugar",
        ),
        (
            "User session authentication token authorization",
            "User authorization tokens and authentication credentials",
            "Hydroponic tomato farming nutrient solution guide",
        ),
        (
            "Refactoring architectural codebase structure",
            "Architectural refactoring of codebases and modules",
            "Mount Everest hiking summit elevation weather",
        ),
        (
            "Vector embeddings cosine similarity nearest neighbor",
            "Nearest neighbor cosine similarity in vector spaces",
            "Classical piano sonata sheet music in B flat minor",
        ),
        (
            "Child process isolation Windows Job Object containment",
            "Windows Job Object process containment and child killing",
            "Ancient Roman pottery excavation in Pompeii ruins",
        ),
        (
            "Async connection pool teardown and database closing",
            "Closing database connections and teardown in async pool",
            "Scuba diving coral reef endangered tropical fish",
        ),
        (
            "Compiler optimization llvm register allocation pass",
            "LLVM register allocation and compiler optimization",
            "Baking sourdough bread starter fermentation timing",
        ),
        (
            "Memory chunk extraction token window overlap",
            "Token chunking window extraction with overlap",
            "Automotive transmission fluid leak replacement",
        ),
        (
            "Cryptographic HMAC SHA256 signature verification",
            "SHA256 HMAC cryptographic signature verifying",
            "Interior decorating living room minimalist furniture",
        ),
        (
            "Tombstone soft deletion rewind invalidation",
            "Soft deletion invalidation with tombstones rewind",
            "Professional tennis tournament grand slam finals",
        ),
    ]

    margins = []
    for anchor, pos, neg in triads:
        v_anc = embedder.embed(anchor)
        v_pos = embedder.embed(pos)
        v_neg = embedder.embed(neg)

        sim_pos = cosine_similarity(v_anc, v_pos)
        sim_neg = cosine_similarity(v_anc, v_neg)
        margin = sim_pos - sim_neg
        margins.append(margin)

        assert sim_pos > sim_neg, f"Semantic discrimination failure: pos={sim_pos} <= neg={sim_neg}"
        assert margin >= 0.20, f"Separation margin {margin:.4f} below 0.20 threshold"

    avg_margin = sum(margins) / len(margins)
    assert avg_margin > 0.50, f"Average margin {avg_margin:.4f} below 0.50"


def test_stress_embedder_zero_network_calls():
    """Verify zero socket connections or external DNS lookups during embedding."""
    embedder = LocalCpuEmbedder(dimension=DEFAULT_DIMENSION)
    network_events = []

    def audit_hook(event, args):
        if event.startswith("socket.") or event in ("urllib.request", "http.client.connect"):
            network_events.append((event, args))

    sys.addaudithook(audit_hook)

    orig_socket = socket.socket
    orig_getaddrinfo = socket.getaddrinfo

    def poison_socket(*args, **kwargs):
        raise RuntimeError("UNAUTHORIZED NETWORK ATTEMPT: socket() called!")

    def poison_getaddrinfo(*args, **kwargs):
        raise RuntimeError("UNAUTHORIZED NETWORK ATTEMPT: getaddrinfo() called!")

    socket.socket = poison_socket
    socket.getaddrinfo = poison_getaddrinfo

    try:
        for i in range(500):
            embedder.embed(f"Zero network verification payload {i} for Project Friday.")
        embedder.embed_batch([f"Batch item {i}" for i in range(20)])
    finally:
        socket.socket = orig_socket
        socket.getaddrinfo = orig_getaddrinfo

    assert len(network_events) == 0, f"Detected network calls: {network_events}"


@pytest.mark.asyncio
async def test_stress_multi_connection_wal_concurrency(tmp_path: Path):
    """Verify SQLite WAL handles concurrent operations across separate connections without locks."""
    db_path = tmp_path / "multi_conn_wal.db"

    # Initialize schema first
    init_mgr = VectorDatabaseManager(db_path)
    await init_mgr.initialize()
    await init_mgr.close()

    async def conn_worker(wid: int):
        mgr = VectorDatabaseManager(db_path)
        await mgr.initialize()
        mem = VectorMemory(mgr)
        try:
            for i in range(5):
                src = MemorySourceModel(
                    source_id=f"src-mc-{wid}-{i}",
                    kind="fact",
                    canonical_locator=f"loc:{wid}:{i}",
                    content_hash=hashlib.sha256(f"{wid}:{i}".encode()).hexdigest(),
                )
                item = MemoryItemModel(
                    item_id=f"item-mc-{wid}-{i}",
                    source_id=src.source_id,
                    text=f"Multi connection WAL item from worker {wid} turn {i}.",
                )
                await mem.ingest(src, [item], auto_process_outbox=True)

                res = await mem.search(f"worker {wid} turn {i}", top_k=2)
                assert len(res) >= 1
        finally:
            await mgr.close()

    # Execute 5 concurrent connection workers
    tasks = [conn_worker(w) for w in range(5)]
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_stress_async_db_teardown_and_connection_cleanup(tmp_path: Path):
    """Verify rapid initialize -> query -> close cycles cleanly teardown without leaks or thread hangs."""
    for cycle in range(10):
        db_path = tmp_path / f"teardown_cycle_{cycle}.db"
        mgr = VectorDatabaseManager(db_path)
        await mgr.initialize()
        mem = VectorMemory(mgr)

        src = MemorySourceModel(
            source_id=f"src-td-{cycle}",
            kind="fact",
            canonical_locator=f"loc:td:{cycle}",
            content_hash=f"htd{cycle}",
        )
        item = MemoryItemModel(
            item_id=f"item-td-{cycle}",
            source_id=src.source_id,
            text=f"Teardown cycle test {cycle}",
        )
        await mem.ingest(src, [item])
        res = await mem.search(f"cycle test {cycle}")
        assert len(res) == 1

        # Strict teardown
        await mgr.close()
        assert mgr._db is None
