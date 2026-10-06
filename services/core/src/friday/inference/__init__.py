"""Inference subsystem for Friday Core."""

from friday.inference.protocol import (
    ChatRequest,
    ChatMessage,
    HealthStatus,
    InferenceBackend,
    InferenceEvent,
    InferenceEventType,
    ModelInfo,
    ModelProfile,
    ModelState,
)
from friday.inference.tabby import TabbyBackend
from friday.inference.mock import MockInferenceBackend
from friday.inference.telemetry import TelemetryProvider, GpuTelemetry
from friday.inference.preflight import check_vram_preflight, PreflightResult
from friday.inference.gaming_mode import GamingModeController, GamingModeStatus

__all__ = [
    "ChatRequest",
    "ChatMessage",
    "HealthStatus",
    "InferenceBackend",
    "InferenceEvent",
    "InferenceEventType",
    "ModelInfo",
    "ModelProfile",
    "ModelState",
    "TabbyBackend",
    "MockInferenceBackend",
    "TelemetryProvider",
    "GpuTelemetry",
    "check_vram_preflight",
    "PreflightResult",
    "GamingModeController",
    "GamingModeStatus",
]
