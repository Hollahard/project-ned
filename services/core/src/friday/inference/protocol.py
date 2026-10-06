"""InferenceBackend protocol and contract types for Friday."""

from enum import Enum
from typing import AsyncIterator, Protocol, runtime_checkable
from pydantic import BaseModel, Field


class ModelState(str, Enum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    READY = "READY"
    DRAINING = "DRAINING"
    UNLOADING = "UNLOADING"
    ERROR = "ERROR"


class ModelProfile(BaseModel):
    name: str
    model_dir: str
    bpw: float = 6.0
    kv_cache_dtype: str = "q6"
    context_length: int = 32768
    max_context_length: int = 65536
    tool_format: str = "auto"
    reasoning_mode: bool = True


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "tabby"
    state: ModelState = ModelState.UNLOADED
    active_profile: ModelProfile | None = None


class HealthStatus(BaseModel):
    healthy: bool
    state: ModelState
    model_id: str | None = None
    vram_used_bytes: int = 0
    vram_total_bytes: int = 0
    details: str = ""


class ChatMessage(BaseModel):
    role: str  # system, user, assistant, tool
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[dict] | None = None
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 4096
    stream: bool = True


class InferenceEventType(str, Enum):
    TOKEN_DELTA = "token_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    FINISH = "finish"
    ERROR = "error"


class InferenceEvent(BaseModel):
    type: InferenceEventType
    content: str = ""
    tool_call: dict | None = None
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


@runtime_checkable
class InferenceBackend(Protocol):
    """Protocol implemented by TabbyBackend and MockInferenceBackend."""

    async def health(self) -> HealthStatus:
        """Check backend health and VRAM telemetry."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        """List available local models."""
        ...

    async def load_model(self, profile: ModelProfile) -> None:
        """Load an EXL3 model profile into VRAM."""
        ...

    async def unload_model(self) -> None:
        """Unload the active model and release all VRAM."""
        ...

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        """Stream generation tokens and tool calls."""
        ...
