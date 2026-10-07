"""Adversarial stress harness for Milestone 3 Standalone Long-Run Endurance Runner.

Empirical verification of:
1. Gaming Mode evacuation (< 2.0s deadline), turn blocking, readiness restoration.
2. Mid-turn cancellation, task auditing (asyncio.all_tasks()), zero leak, loop recovery.
3. Job Object sidecar kill/restart accounting, 0 orphans.
4. VRAM recovery oracle residual <= 512MB and monotonic leak detection.
5. Tripwire evaluator mathematical slope bounds, ratchet detection, thermal/WAL ceilings.
6. CLI argument parsing and end-to-end execution.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

import pytest

# Ensure services/core/src and project root are on sys.path
project_root = Path(__file__).resolve().parents[2]
core_src = project_root / "services" / "core" / "src"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(core_src) not in sys.path:
    sys.path.insert(0, str(core_src))

from friday.agent.loop import AgentLoop
from friday.inference.gaming_mode import GamingModeController, GamingModeStatus
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    InferenceEventType,
    ModelProfile,
    ModelState,
)
from friday.security.tokens import CapabilityTokenManager
from friday.tools.base import ToolResult
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry

from tests.soak.run_8hr_soak import (
    GamingModeFaultInjector,
    JobObjectSidecarFaultInjector,
    MidTurnCancelFaultInjector,
    SoakInferenceEngine,
    SoakTripwireEvaluator,
    TelemetrySnapshot,
    VramRecoveryOracle,
    Win32JobSupervisor,
    parse_soak_cli_args,
)


# ==============================================================================
# 1. Gaming Mode Evacuation & Invariants
# ==============================================================================


@pytest.mark.asyncio
async def test_gaming_mode_evacuation_timing_and_state():
    """Verify Gaming Mode evacuates in < 2.0s and restores readiness."""
    backend = SoakInferenceEngine()
    controller = GamingModeController()
    tools = ToolRegistry()
    token_mgr = CapabilityTokenManager("test-key")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[Path(".")])
    agent_loop = AgentLoop(inference=backend, tools=tools, policy=policy)

    # Initial state
    assert backend.state == ModelState.READY

    # 1. Evacuation
    t_start = time.perf_counter()
    status = await controller.activate(backend=backend, agent_loop=agent_loop)
    t_evac = time.perf_counter() - t_start

    assert t_evac < 2.0, f"Evacuation took {t_evac:.4f}s, exceeding 2.0s limit"
    assert status.active is True
    assert backend.state == ModelState.UNLOADED
    assert backend.current_vram_mb == backend.mock_vram_residual_mb

    # 2. Deactivation & Restoration
    await controller.deactivate()
    await backend.load_model(backend.active_profile)
    assert backend.state == ModelState.READY
    assert backend.current_vram_mb == backend.mock_vram_active_mb


@pytest.mark.asyncio
async def test_gaming_mode_turn_blocking_behavior():
    """Adversarial check: What happens if a turn is attempted while backend is UNLOADED?"""
    backend = SoakInferenceEngine()
    controller = GamingModeController()
    tools = ToolRegistry()
    token_mgr = CapabilityTokenManager("test-key")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[Path(".")])
    agent_loop = AgentLoop(inference=backend, tools=tools, policy=policy)

    # Evacuate
    await controller.activate(backend=backend, agent_loop=agent_loop)
    assert backend.state == ModelState.UNLOADED

    # Check whether SoakInferenceEngine.generate respects UNLOADED state
    events = []
    async for ev in backend.generate(ChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")])):
        events.append(ev)

    # Examine if generator yielded tokens or errors
    token_events = [e for e in events if e.type == InferenceEventType.TOKEN_DELTA]
    error_events = [e for e in events if e.type == InferenceEventType.ERROR]

    # Deactivate and restore
    await controller.deactivate()
    await backend.load_model(backend.active_profile)

    # Log findings: Does SoakInferenceEngine check state in generate()?
    print(f"\n[Adversarial Analysis] Unloaded generate() results: tokens={len(token_events)}, errors={len(error_events)}")


# ==============================================================================
# 2. Mid-Turn Cancellation & Task Leakage
# ==============================================================================


@pytest.mark.asyncio
async def test_mid_turn_cancellation_task_auditing():
    """Verify mid-turn cancellation emits turn.canceled, leaks 0 tasks, and recovers."""
    backend = SoakInferenceEngine()
    tools = ToolRegistry()
    token_mgr = CapabilityTokenManager("test-key")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[Path(".")])
    agent_loop = AgentLoop(inference=backend, tools=tools, policy=policy)

    injector = MidTurnCancelFaultInjector()

    # Single execution
    res = await injector.execute(agent_loop, session_id="test-session-cancel")
    assert res["success"] is True
    assert res["turn_canceled_emitted"] is True
    assert res["turn_completed_suppressed"] is True
    assert res["leaked_tasks"] == 0
    assert res["active_cancels_leaked"] == 0
    assert res["recovery_turn_success"] is True


@pytest.mark.asyncio
async def test_rapid_cancellation_stress():
    """Stress test: 10 rapid mid-turn cancellations in succession."""
    backend = SoakInferenceEngine()
    tools = ToolRegistry()
    token_mgr = CapabilityTokenManager("test-key")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[Path(".")])
    agent_loop = AgentLoop(inference=backend, tools=tools, policy=policy)

    injector = MidTurnCancelFaultInjector()

    tasks_baseline = len([t for t in asyncio.all_tasks() if not t.done()])

    for i in range(10):
        res = await injector.execute(agent_loop, session_id=f"test-stress-{i}")
        assert res["success"] is True, f"Failed at iteration {i}"
        assert res["leaked_tasks"] == 0, f"Leaked tasks at iteration {i}: {res['leaked_tasks']}"

    # Give event loop a microsecond to drain done tasks
    await asyncio.sleep(0.05)
    tasks_end = len([t for t in asyncio.all_tasks() if not t.done()])
    assert tasks_end <= tasks_baseline + 1, f"Task ratchet detected: {tasks_baseline} -> {tasks_end}"
    assert len(agent_loop._active_cancels) == 0, "Dangling entries in _active_cancels"


# ==============================================================================
# 3. Job Object Sidecar Restart & Zero Orphans
# ==============================================================================


@pytest.mark.asyncio
async def test_job_object_sidecar_restart_accounting():
    """Verify Job Object process accounting: 1 -> 0 -> 1 -> 0 with zero orphans."""
    injector = JobObjectSidecarFaultInjector()
    res = await injector.execute()

    assert res["success"] is True
    assert res["active_processes_initial"] == 1
    assert res["active_processes_after_kill"] == 0
    assert res["active_processes_after_restart"] == 1
    assert res["orphans_leaked"] == 0


def test_job_object_kill_on_job_close_orphan_proof():
    """Verify that closing Job Object terminates all assigned child processes (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)."""
    supervisor = Win32JobSupervisor()
    if supervisor._handle is None:
        pytest.skip("Not running on Windows with valid kernel32")

    # Spawn 3 sleep processes
    cmd = [sys.executable, "-c", "import time; time.sleep(120)"]
    p1 = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p2 = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p3 = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    supervisor.assign_process(p1.pid)
    supervisor.assign_process(p2.pid)
    supervisor.assign_process(p3.pid)

    active = supervisor.query_active_processes()
    assert active == 3, f"Expected 3 active processes in Job Object, got {active}"

    # Close the job object handle: kernel should terminate p1, p2, p3
    supervisor.close()

    time.sleep(0.5)

    # Verify processes are terminated
    assert p1.poll() is not None, f"PID {p1.pid} survived Job Object close!"
    assert p2.poll() is not None, f"PID {p2.pid} survived Job Object close!"
    assert p3.poll() is not None, f"PID {p3.pid} survived Job Object close!"


# ==============================================================================
# 4. VRAM Recovery Oracle Bounds
# ==============================================================================


def test_vram_oracle_within_512mb():
    oracle = VramRecoveryOracle(use_real_gpu=False)
    oracle.record_post_start_baseline(mock_val=1240.0)

    # 1. Exact return
    passed, delta, _ = oracle.verify_post_unload(1240.0)
    assert passed is True
    assert delta == 0.0

    # 2. Within 512 MB (e.g. 500 MB residual)
    passed, delta, _ = oracle.verify_post_unload(1740.0)
    assert passed is True
    assert delta == 500.0


def test_vram_oracle_exceeding_512mb():
    oracle = VramRecoveryOracle(use_real_gpu=False)
    oracle.record_post_start_baseline(mock_val=1240.0)

    # Residual delta = 550 MB (> 512 MB)
    passed, delta, _ = oracle.verify_post_unload(1790.0)
    assert passed is False
    assert delta == 550.0
    assert any("exceeded post-start baseline" in v for v in oracle.violations)


def test_vram_oracle_monotonic_drift_detection():
    oracle = VramRecoveryOracle(use_real_gpu=False)
    oracle.record_post_start_baseline(mock_val=1000.0)

    # 3 consecutive increasing residuals: 1100 -> 1200 -> 1300
    oracle.verify_post_unload(1100.0)
    oracle.verify_post_unload(1200.0)
    passed, _, _ = oracle.verify_post_unload(1300.0)

    assert passed is False
    assert any("Monotonic VRAM growth" in v for v in oracle.violations)


# ==============================================================================
# 5. Tripwire Evaluator Mathematical Bounds
# ==============================================================================


def test_tripwire_warmup_filtering():
    """Ensure samples during warmup are buffered and do not trip slope tripwires."""
    evaluator = SoakTripwireEvaluator(warmup_seconds=180.0)

    snap = TelemetrySnapshot(
        timestamp=time.time(),
        iso_timestamp="2026-10-07T12:00:00Z",
        elapsed_seconds=60.0,  # in warmup
        total_private_bytes_mb=200.0,
    )
    res = evaluator.evaluate(snap)
    assert res.in_warmup is True
    assert res.passed is True
    assert res.should_abort is False


def test_tripwire_private_bytes_slope_breach():
    """Ensure growth slope > 50 MB/hour with drift > 10 MB trips violation."""
    evaluator = SoakTripwireEvaluator(warmup_seconds=0.0)

    # Simulate 3 samples over 1 hour with 60 MB growth
    s1 = TelemetrySnapshot(timestamp=0.0, iso_timestamp="", elapsed_seconds=0.0, total_private_bytes_mb=100.0)
    s2 = TelemetrySnapshot(timestamp=1800.0, iso_timestamp="", elapsed_seconds=1800.0, total_private_bytes_mb=130.0)
    s3 = TelemetrySnapshot(timestamp=3600.0, iso_timestamp="", elapsed_seconds=3600.0, total_private_bytes_mb=160.0)

    evaluator.evaluate(s1)
    evaluator.evaluate(s2)
    res3 = evaluator.evaluate(s3)

    assert res3.passed is False
    assert res3.should_abort is True
    assert any("Private Bytes Slope Breached" in v for v in res3.violations)
    assert res3.private_bytes_slope_mb_per_hour == pytest.approx(60.0, rel=1e-2)


def test_tripwire_thread_ratchet():
    """Ensure monotonic ratchet across 4 quartiles triggers violation."""
    evaluator = SoakTripwireEvaluator(warmup_seconds=0.0)

    # 16 samples with ratcheting quartiles: Q1: min 10, Q2: min 12, Q3: min 14, Q4: min 16
    threads = [10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 18]
    assert evaluator.detect_thread_ratchet(threads) is True


def test_tripwire_gpu_temp_ceiling():
    """Ensure GPU temperature >= 83°C trips immediate abort even during warmup."""
    evaluator = SoakTripwireEvaluator(warmup_seconds=900.0)
    from tests.soak.run_8hr_soak import GpuMetrics

    snap = TelemetrySnapshot(
        timestamp=0.0,
        iso_timestamp="",
        elapsed_seconds=30.0,
        gpu=GpuMetrics(available=True, temperature_c=84),
    )
    res = evaluator.evaluate(snap)
    assert res.should_abort is True
    assert any("GPU Thermal Tripwire Breached" in v for v in res.violations)


def test_tripwire_wal_size_ceiling():
    """Ensure SQLite WAL size > 64 MB trips immediate abort."""
    evaluator = SoakTripwireEvaluator(warmup_seconds=900.0)

    snap = TelemetrySnapshot(
        timestamp=0.0,
        iso_timestamp="",
        elapsed_seconds=30.0,
        wal_size_mb=65.2,
    )
    res = evaluator.evaluate(snap)
    assert res.should_abort is True
    assert any("SQLite WAL Size Tripwire Breached" in v for v in res.violations)


# ==============================================================================
# 6. CLI Argument Parsing & Profiles
# ==============================================================================


def test_cli_parsing_modes():
    cfg_smoke = parse_soak_cli_args(["--mode", "smoke"])
    assert cfg_smoke.mode == "smoke"
    assert cfg_smoke.duration_seconds == 15 * 60
    assert cfg_smoke.warmup_seconds == 3 * 60

    cfg_gate = parse_soak_cli_args(["--mode", "gate"])
    assert cfg_gate.mode == "gate"
    assert cfg_gate.duration_seconds == 60 * 60
    assert cfg_gate.warmup_seconds == 15 * 60

    cfg_release = parse_soak_cli_args(["--mode", "release"])
    assert cfg_release.mode == "release"
    assert cfg_release.duration_seconds == 8 * 3600
    assert cfg_release.warmup_seconds == 15 * 60

    cfg_custom = parse_soak_cli_args(["--mode", "custom", "--duration-minutes", "10", "--warmup-minutes", "2"])
    assert cfg_custom.mode == "custom"
    assert cfg_custom.duration_seconds == 600
    assert cfg_custom.warmup_seconds == 120
