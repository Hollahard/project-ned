"""TabbyAPI inference backend for Friday Core (ExLlamaV3 on 127.0.0.1)."""

import json
import logging
from typing import AsyncIterator
import httpx

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

logger = logging.getLogger(__name__)


class TabbyBackend(InferenceBackend):
    """Inference backend communicating with the local TabbyAPI sidecar."""

    def __init__(self, base_url: str = "http://127.0.0.1:5000", admin_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self.state = ModelState.UNLOADED
        self.active_profile: ModelProfile | None = None
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0),
            headers={"Authorization": f"Bearer {self.admin_key}"} if self.admin_key else {},
        )

    async def health(self) -> HealthStatus:
        """Query TabbyAPI health and GPU telemetry."""
        try:
            resp = await self._client.get("/health")
            if resp.status_code == 200:
                data = resp.json()
                return HealthStatus(
                    healthy=True,
                    state=self.state,
                    model_id=self.active_profile.name if self.active_profile else None,
                    vram_used_bytes=data.get("vram_used", 0),
                    vram_total_bytes=data.get("vram_total", 0),
                    details=data.get("status", "running"),
                )
            return HealthStatus(
                healthy=False,
                state=ModelState.ERROR,
                details=f"Tabby health check returned {resp.status_code}",
            )
        except Exception as exc:
            logger.debug("Failed to connect to TabbyAPI at %s: %s", self.base_url, exc)
            return HealthStatus(
                healthy=False,
                state=ModelState.UNLOADED,
                details=f"TabbyAPI unreachable: {exc}",
            )

    async def list_models(self) -> list[ModelInfo]:
        """List models available in TabbyAPI."""
        try:
            resp = await self._client.get("/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                return [
                    ModelInfo(
                        id=m["id"],
                        created=m.get("created", 0),
                        owned_by=m.get("owned_by", "tabby"),
                        state=self.state if self.active_profile and m["id"] == self.active_profile.name else ModelState.UNLOADED,
                    )
                    for m in data.get("data", [])
                ]
            return []
        except Exception as exc:
            logger.error("Error listing models from TabbyAPI: %s", exc)
            return []

    async def load_model(self, profile: ModelProfile) -> None:
        """Load an EXL3 model via TabbyAPI admin endpoint."""
        self.state = ModelState.LOADING
        logger.info("Loading model profile '%s' in TabbyAPI", profile.name)
        payload = {
            "model_name": profile.name,
            "max_seq_len": profile.context_length,
            "cache_mode": profile.kv_cache_dtype,
        }
        try:
            resp = await self._client.post("/v1/model/load", json=payload, timeout=60.0)
            if resp.status_code == 200:
                self.active_profile = profile
                self.state = ModelState.READY
                logger.info("Model '%s' successfully loaded and READY", profile.name)
            else:
                self.state = ModelState.ERROR
                raise RuntimeError(f"Failed to load model: {resp.text}")
        except Exception as exc:
            self.state = ModelState.ERROR
            logger.error("Exception loading model in TabbyAPI: %s", exc)
            raise

    async def unload_model(self) -> None:
        """Unload active model to immediately free VRAM."""
        self.state = ModelState.UNLOADING
        logger.info("Unloading active model from TabbyAPI to free VRAM")
        try:
            resp = await self._client.post("/v1/model/unload", timeout=30.0)
            if resp.status_code == 200:
                self.active_profile = None
                self.state = ModelState.UNLOADED
                logger.info("Model unloaded successfully. VRAM released.")
            else:
                self.state = ModelState.ERROR
                raise RuntimeError(f"Failed to unload model: {resp.text}")
        except Exception as exc:
            self.state = ModelState.ERROR
            logger.error("Exception unloading model: %s", exc)
            raise

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        """Stream completions from TabbyAPI /v1/chat/completions."""
        payload = {
            "model": request.model,
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.tools:
            payload["tools"] = request.tools

        try:
            async with self._client.stream("POST", "/v1/chat/completions", json=payload, timeout=httpx.Timeout(connect=5.0, read=300.0, write=5.0, pool=5.0)) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    yield InferenceEvent(
                        type=InferenceEventType.ERROR,
                        content=f"Inference error {response.status_code}: {err_text.decode('utf-8', errors='replace')}",
                    )
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        if "content" in delta and delta["content"]:
                            yield InferenceEvent(
                                type=InferenceEventType.TOKEN_DELTA,
                                content=delta["content"],
                            )

                        if "tool_calls" in delta and delta["tool_calls"]:
                            for tc in delta["tool_calls"]:
                                yield InferenceEvent(
                                    type=InferenceEventType.TOOL_CALL,
                                    tool_call=tc,
                                )

                        if finish_reason:
                            yield InferenceEvent(
                                type=InferenceEventType.FINISH,
                                finish_reason=finish_reason,
                            )
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.error("Inference server error: %s", exc)
            yield InferenceEvent(
                type=InferenceEventType.ERROR,
                content=f"Inference backend unavailable: {exc}",
            )

    async def close(self) -> None:
        await self._client.aclose()
