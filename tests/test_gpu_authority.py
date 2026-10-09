"""Hard verification test suite for Phase 5: Gaming Mode and GPU Resource Authority.

Verifies:
1. Centralized GPU Authority:
   - RTX 5090 32 GiB single worker authority across Primary LLM, Draft, Vision, Embeddings, Speech, and Profiler.
   - Over-allocation rejected with insufficient VRAM error.
2. Admission Barrier:
   - When Gaming Mode is requested/active, all incoming generation, embed, and worker requests
     immediately receive GATEWAY_BUSY_GAMING_MODE without waiting in an unmanaged queue.
3. Cancellation & Drain Protocol:
   - Active streams receive immediate cancellation frames.
   - In-flight worker leases marked inactive and drained.
   - 100% of VRAM is evacuated to 0 bytes baseline.
4. State Restore & Crash Recovery:
   - Cold crash recovery preserves gaming mode state and lease history.
5. Windows Async Teardown Hygiene:
   - Async yield fixtures explicitly await close() ensuring zero thread hangs or subshell blocks.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from friday.inference.gpu_authority import (
    GATEWAY_BUSY_GAMING_MODE,
    RTX_5090_TOTAL_VRAM_BYTES,
    GamingModeState,
    GatewayBusyGamingModeError,
    GpuAuthority,
    GpuLease,
    GpuWorkerType,
)

# ---------------------------------------------------------------------------
# Async Teardown Hygiene Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def gpu_authority(tmp_path: Path) -> AsyncGenerator[GpuAuthority, None]:
    """Asynchronous yield fixture ensuring 100% clean teardown of background workers."""
    persist_path = tmp_path / "gpu_state.json"
    authority = GpuAuthority(
        total_vram_bytes=RTX_5090_TOTAL_VRAM_BYTES,
        persistence_path=persist_path,
    )
    try:
        yield authority
    finally:
        # Mandatory Windows async cleanup to prevent hanging subshells
        await authority.close()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_gpu_worker_authority_and_vram_accounting(
    gpu_authority: GpuAuthority,
) -> None:
    """Tests RTX 5090 32 GiB capacity accounting across multiple worker types."""
    assert gpu_authority.total_vram_bytes == RTX_5090_TOTAL_VRAM_BYTES
    assert gpu_authority.get_allocated_vram_bytes() == 0
    assert gpu_authority.get_available_vram_bytes() == RTX_5090_TOTAL_VRAM_BYTES

    # Allocate Primary LLM (16 GiB)
    llm_vram = 16 * 1024 * 1024 * 1024
    lease_llm = await gpu_authority.request_admission(
        GpuWorkerType.PRIMARY_LLM, llm_vram
    )
    assert lease_llm.active
    assert lease_llm.worker == GpuWorkerType.PRIMARY_LLM
    assert gpu_authority.get_allocated_vram_bytes() == llm_vram
    assert (
        gpu_authority.get_available_vram_bytes() == RTX_5090_TOTAL_VRAM_BYTES - llm_vram
    )

    # Allocate Draft Model (4 GiB)
    draft_vram = 4 * 1024 * 1024 * 1024
    lease_draft = await gpu_authority.request_admission(
        GpuWorkerType.DRAFT_MODEL, draft_vram
    )
    assert lease_draft.active

    # Allocate Embeddings (2 GiB)
    embed_vram = 2 * 1024 * 1024 * 1024
    lease_embed = await gpu_authority.request_admission(
        GpuWorkerType.EMBEDDINGS, embed_vram
    )
    assert lease_embed.active

    total_allocated = llm_vram + draft_vram + embed_vram
    assert gpu_authority.get_allocated_vram_bytes() == total_allocated

    # Over-allocation beyond 32 GiB must be rejected
    excess_vram = 15 * 1024 * 1024 * 1024  # 22 + 15 = 37 GiB > 32 GiB
    with pytest.raises(ValueError, match="Insufficient VRAM"):
        await gpu_authority.request_admission(GpuWorkerType.VISION, excess_vram)

    # Release individual lease
    await gpu_authority.release_lease(lease_embed.lease_id)
    assert not gpu_authority.leases[lease_embed.lease_id].active
    assert gpu_authority.get_allocated_vram_bytes() == total_allocated - embed_vram


@pytest.mark.asyncio
async def test_admission_barrier_rejects_with_gateway_busy_gaming_mode(
    gpu_authority: GpuAuthority,
) -> None:
    """Verifies immediate admission barrier returns GATEWAY_BUSY_GAMING_MODE."""
    # Pre-allocate one worker
    await gpu_authority.request_admission(
        GpuWorkerType.PRIMARY_LLM, 10 * 1024 * 1024 * 1024
    )

    # Engage Gaming Mode
    report = await gpu_authority.activate_gaming_mode()
    assert report.cancelled_leases == 1
    assert gpu_authority.is_gaming_mode_active()
    assert gpu_authority.gaming_mode == GamingModeState.ACTIVE

    # All worker requests must be immediately rejected with GATEWAY_BUSY_GAMING_MODE
    all_workers = [
        GpuWorkerType.PRIMARY_LLM,
        GpuWorkerType.DRAFT_MODEL,
        GpuWorkerType.VISION,
        GpuWorkerType.EMBEDDINGS,
        GpuWorkerType.SPEECH_AUDIO,
        GpuWorkerType.PROFILER,
    ]

    for worker in all_workers:
        with pytest.raises(GatewayBusyGamingModeError) as exc_info:
            await gpu_authority.request_admission(worker, 1024 * 1024 * 1024)
        assert exc_info.value.code == GATEWAY_BUSY_GAMING_MODE
        assert GATEWAY_BUSY_GAMING_MODE in str(exc_info.value)
        assert exc_info.value.worker == worker

    # Deactivating Gaming Mode lifts the barrier
    await gpu_authority.deactivate_gaming_mode()
    assert not gpu_authority.is_gaming_mode_active()

    resumed_lease = await gpu_authority.request_admission(
        GpuWorkerType.PRIMARY_LLM, 8 * 1024 * 1024 * 1024
    )
    assert resumed_lease.active


@pytest.mark.asyncio
async def test_cancellation_and_drain_protocol(
    gpu_authority: GpuAuthority,
) -> None:
    """Verifies active stream cancellation frames and 0 bytes baseline evacuation."""
    cancelled_leases: list[GpuLease] = []

    def on_cancelled(lease: GpuLease) -> None:
        cancelled_leases.append(lease)

    remove_cb = gpu_authority.register_cancellation_callback(on_cancelled)

    # Allocate workers
    l1 = await gpu_authority.request_admission(
        GpuWorkerType.PRIMARY_LLM, 14 * 1024 * 1024 * 1024
    )
    l2 = await gpu_authority.request_admission(
        GpuWorkerType.VISION, 6 * 1024 * 1024 * 1024
    )
    l3 = await gpu_authority.request_admission(
        GpuWorkerType.PROFILER, 2 * 1024 * 1024 * 1024
    )

    assert gpu_authority.get_allocated_vram_bytes() == 22 * 1024 * 1024 * 1024

    # Trigger activation -> triggers cancellation & drain
    report = await gpu_authority.activate_gaming_mode()

    assert report.cancelled_leases == 3
    assert report.vram_freed_bytes == 22 * 1024 * 1024 * 1024
    assert len(cancelled_leases) == 3
    assert {c.lease_id for c in cancelled_leases} == {
        l1.lease_id,
        l2.lease_id,
        l3.lease_id,
    }

    # Verified 0 VRAM baseline
    assert gpu_authority.get_allocated_vram_bytes() == 0
    assert gpu_authority.get_available_vram_bytes() == RTX_5090_TOTAL_VRAM_BYTES

    remove_cb()


@pytest.mark.asyncio
async def test_cold_crash_recovery_and_persistence(tmp_path: Path) -> None:
    """Verifies state preservation and crash recovery across restarts."""
    persist_path = tmp_path / "gpu_authority_crash.json"

    # 1. Initialize instance and configure Gaming Mode
    auth1 = GpuAuthority(
        total_vram_bytes=RTX_5090_TOTAL_VRAM_BYTES,
        persistence_path=persist_path,
    )
    lease = await auth1.request_admission(
        GpuWorkerType.PRIMARY_LLM, 16 * 1024 * 1024 * 1024
    )
    await auth1.activate_gaming_mode()
    assert auth1.gaming_mode == GamingModeState.ACTIVE
    await auth1.close()

    # 2. Reconstruct from cold persistence path
    auth2 = GpuAuthority(
        total_vram_bytes=RTX_5090_TOTAL_VRAM_BYTES,
        persistence_path=persist_path,
    )
    try:
        assert auth2.gaming_mode == GamingModeState.ACTIVE
        assert auth2.is_gaming_mode_active()
        assert auth2.get_allocated_vram_bytes() == 0
        assert lease.lease_id in auth2.leases
        assert not auth2.leases[lease.lease_id].active

        # Barrier remains locked after cold recovery
        with pytest.raises(GatewayBusyGamingModeError):
            await auth2.request_admission(GpuWorkerType.EMBEDDINGS, 1024 * 1024 * 1024)
    finally:
        await auth2.close()
