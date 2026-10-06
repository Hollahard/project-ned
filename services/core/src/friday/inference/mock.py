"""Mock inference backend for testing Friday without a GPU."""

import asyncio
from typing import AsyncIterator
from friday.inference.protocol import (
    ChatRequest,
    HealthStatus,
    InferenceBackend,
    InferenceEvent,
    InferenceEventType,
    ModelInfo,
    ModelProfile,
    ModelState,
)


class MockInferenceBackend(InferenceBackend):
    """Mock backend providing deterministic streaming responses for tests."""

    def __init__(self) -> None:
        self.state = ModelState.UNLOADED
        self.active_profile: ModelProfile | None = None
        self.mock_responses: list[str] = ["Hello from Project Friday mock!"]
        self.mock_tool_calls: list[dict] | None = None

    async def health(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            state=self.state,
            model_id=self.active_profile.name if self.active_profile else None,
            vram_used_bytes=1024 * 1024 * 1024 if self.state == ModelState.READY else 0,
            vram_total_bytes=32 * 1024 * 1024 * 1024,
            details="Mock backend operational",
        )

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id="mock-qwen-27b",
                state=self.state,
                active_profile=self.active_profile,
            )
        ]

    async def load_model(self, profile: ModelProfile) -> None:
        self.state = ModelState.LOADING
        await asyncio.sleep(0.01)
        self.active_profile = profile
        self.state = ModelState.READY

    async def unload_model(self) -> None:
        self.state = ModelState.UNLOADING
        await asyncio.sleep(0.01)
        self.active_profile = None
        self.state = ModelState.UNLOADED

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        if self.state != ModelState.READY:
            yield InferenceEvent(
                type=InferenceEventType.ERROR,
                content="Model not ready",
            )
            return

        # Check if we should emit a tool call
        if self.mock_tool_calls:
            for tool_call in self.mock_tool_calls:
                yield InferenceEvent(
                    type=InferenceEventType.TOOL_CALL,
                    tool_call=tool_call,
                )
            yield InferenceEvent(
                type=InferenceEventType.FINISH,
                finish_reason="tool_calls",
                prompt_tokens=10,
                completion_tokens=25,
            )
            return

        response_text = self.mock_responses[0] if self.mock_responses else "Response"
        tokens = response_text.split(" ")
        for token in tokens:
            yield InferenceEvent(
                type=InferenceEventType.TOKEN_DELTA,
                content=token + " ",
            )
            await asyncio.sleep(0.001)

        yield InferenceEvent(
            type=InferenceEventType.FINISH,
            finish_reason="stop",
            prompt_tokens=len(request.messages) * 5,
            completion_tokens=len(tokens),
        )
