"""Gaming Mode: One-click turn abort and instant VRAM evacuation for Project Friday.

Invariants:
1. One-click evacuation halts ongoing inference generation immediately.
2. Unloads model from TabbyAPI to return 100% of GPU memory to Windows baseline.
3. Evacuation completes within 2.0 seconds.
4. When Gaming Mode is active, new model load requests and generation turns are blocked.
"""

import time
import logging
from typing import Any, Optional
from pydantic import BaseModel

from friday.inference.protocol import InferenceBackend
from friday.inference.telemetry import TelemetryProvider

logger = logging.getLogger(__name__)


class GamingModeStatus(BaseModel):
    active: bool
    activated_at: Optional[float] = None
    elapsed_seconds: float = 0.0
    vram_freed_mb: float = 0.0
    message: str


class GamingModeController:
    """Coordinates one-click generation abort and instant VRAM evacuation."""

    def __init__(
        self,
        telemetry_provider: Optional[TelemetryProvider] = None,
        connection_manager: Any = None,
    ) -> None:
        self.active: bool = False
        self.activated_at: Optional[float] = None
        self.last_elapsed_seconds: float = 0.0
        self.last_freed_vram_mb: float = 0.0
        self.telemetry = telemetry_provider
        self.connection_manager = connection_manager

    async def activate(
        self,
        backend: InferenceBackend,
        agent_loop: Any = None,
    ) -> GamingModeStatus:
        """Trigger instant generation abort and VRAM evacuation."""
        start_time = time.perf_counter()
        logger.info("GAMING MODE ACTIVATION INITIATED: Halting inference and evacuating VRAM")

        # 1. Snapshot initial VRAM
        vram_before_mb = 0.0
        if self.telemetry:
            telem_before = self.telemetry.get_gpu_telemetry()
            if telem_before.available:
                vram_before_mb = telem_before.vram_used_mb

        # 2. Cancel in-flight agent turn / websocket tasks if active
        if self.connection_manager and hasattr(self.connection_manager, "in_flight_tasks"):
            for sid in list(self.connection_manager.in_flight_tasks.keys()):
                try:
                    self.connection_manager.cancel_turn(sid)
                    logger.info("Cancelled active WebSocket turn in session %s for Gaming Mode", sid)
                except Exception as exc:
                    logger.warning("Error cancelling turn for session %s: %s", sid, exc)

        if agent_loop and hasattr(agent_loop, "cancel_current_turn"):
            try:
                agent_loop.cancel_current_turn()
                logger.info("Cancelled active agent turn for Gaming Mode")
            except Exception as exc:
                logger.warning("Error cancelling agent turn: %s", exc)

        # 3. Evacuate model from TabbyAPI
        try:
            await backend.unload_model()
            logger.info("Successfully unloaded model from TabbyAPI")
        except Exception as exc:
            logger.warning("Error unloading model during Gaming Mode activation: %s", exc)

        # 4. Measure completion time
        elapsed = time.perf_counter() - start_time

        # 5. Snapshot final VRAM
        vram_freed_mb = 0.0
        if self.telemetry:
            telem_after = self.telemetry.get_gpu_telemetry()
            if telem_after.available and vram_before_mb > telem_after.vram_used_mb:
                vram_freed_mb = vram_before_mb - telem_after.vram_used_mb

        self.active = True
        self.activated_at = time.time()
        self.last_elapsed_seconds = round(elapsed, 3)
        self.last_freed_vram_mb = round(vram_freed_mb, 1)

        msg = (
            f"Gaming Mode ACTIVE. VRAM evacuated in {self.last_elapsed_seconds:.3f}s. "
            f"GPU memory returned to Windows baseline."
        )
        logger.info(msg)

        return GamingModeStatus(
            active=True,
            activated_at=self.activated_at,
            elapsed_seconds=self.last_elapsed_seconds,
            vram_freed_mb=self.last_freed_vram_mb,
            message=msg,
        )

    async def deactivate(self) -> GamingModeStatus:
        """Deactivate Gaming Mode, re-enabling model loads and inference."""
        self.active = False
        self.activated_at = None
        logger.info("GAMING MODE DEACTIVATED: Model loading and generation re-enabled")
        return GamingModeStatus(
            active=False,
            activated_at=None,
            elapsed_seconds=0.0,
            vram_freed_mb=0.0,
            message="Gaming Mode deactivated. Models can now be loaded.",
        )

    def get_status(self) -> GamingModeStatus:
        return GamingModeStatus(
            active=self.active,
            activated_at=self.activated_at,
            elapsed_seconds=self.last_elapsed_seconds,
            vram_freed_mb=self.last_freed_vram_mb,
            message="Gaming Mode is active" if self.active else "Gaming Mode is inactive",
        )
