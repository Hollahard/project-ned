"""REST/IPC connector for TabbyAPI model loading, unloading, context sizing, batching, and KV-cache settings.

Enforces:
1. Zero direct engine imports (no exllamav3/exllamav2 imports in Core).
2. Backend qualification order: ExLlama V3 primary, ExLlama V2 secondary fallback.
3. Strict parameter extraction and validation against requested load profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BackendType(StrEnum):
    EXLLAMAV3 = "exllamav3"
    EXLLAMAV2 = "exllamav2"

    @classmethod
    def qualification_order(cls) -> list[BackendType]:
        """Qualification order: EXL3 primary, EXL2 secondary fallback."""
        return [cls.EXLLAMAV3, cls.EXLLAMAV2]


def normalize_cache_mode(value: str) -> str:
    """Normalizes KV-cache precision string to TabbyAPI expected representation."""
    if not isinstance(value, str):
        raise ValueError("cache_mode must be a string")
    normalized = value.strip().upper()
    aliases = {
        "FP16": "FP16",
        "Q4": "4,4",
        "4,4": "4,4",
        "Q6": "6,6",
        "6,6": "6,6",
        "Q8": "8,8",
        "8,8": "8,8",
    }
    if normalized in aliases:
        return aliases[normalized]
    match = re.fullmatch(r"([2-8])\s*,\s*([2-8])", normalized)
    if match:
        return f"{match[1]},{match[2]}"
    raise ValueError(f"Unsupported cache_mode: {value}")


@dataclass(frozen=True)
class BrokerLoadProfile:
    model_name: str
    backend: BackendType = BackendType.EXLLAMAV3
    max_seq_len: int = 4096
    cache_size: int = 4096
    cache_mode: str = "6,6"
    max_batch_size: int = 1
    chunk_size: int = 2048
    use_vision: bool = False
    draft_mode: str = "disabled"

    def __post_init__(self) -> None:
        if self.cache_size < self.max_seq_len:
            raise ValueError("cache_size must cover max_seq_len")
        if self.max_seq_len <= 0 or self.cache_size <= 0:
            raise ValueError("context length and cache size must be positive")
        object.__setattr__(self, "cache_mode", normalize_cache_mode(self.cache_mode))

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "backend": str(self.backend),
            "max_seq_len": self.max_seq_len,
            "cache_size": self.cache_size,
            "cache_mode": self.cache_mode,
            "max_batch_size": self.max_batch_size,
            "chunk_size": self.chunk_size,
            "use_vision": self.use_vision,
            "draft_model": {"draft_mode": self.draft_mode},
        }


@dataclass(frozen=True)
class EffectiveParameters:
    model_name: str
    backend: BackendType
    max_seq_len: int
    cache_size: int
    cache_mode: str
    max_batch_size: int
    chunk_size: int
    use_vision: bool
    draft_enabled: bool


class TabbyBrokerClient:
    """Async client connector communicating with the TabbyAPI broker."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5000",
        admin_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        headers = {"Authorization": f"Bearer {admin_key}"} if admin_key else {}
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self._active_profile: BrokerLoadProfile | None = None
        self._effective_params: EffectiveParameters | None = None

    @property
    def active_profile(self) -> BrokerLoadProfile | None:
        return self._active_profile

    @property
    def effective_parameters(self) -> EffectiveParameters | None:
        return self._effective_params

    async def qualify_backend(
        self, supported_backends: list[BackendType] | None = None
    ) -> BackendType:
        """Determines qualifying backend following EXL3-first priority order."""
        available = (
            supported_backends
            if supported_backends is not None
            else BackendType.qualification_order()
        )
        for candidate in BackendType.qualification_order():
            if candidate in available:
                return candidate
        raise RuntimeError("No supported backend available")

    async def load_model(self, profile: BrokerLoadProfile) -> EffectiveParameters:
        """Invokes /v1/model/load and validates effective parameters."""
        payload = profile.to_payload()
        resp = await self._client.post("/v1/model/load", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Model load failed: {resp.status_code} - {resp.text}")

        # Extract effective parameters from observation endpoints
        model_info_resp = await self._client.get("/v1/model")
        props_resp = await self._client.get("/props")

        if model_info_resp.status_code != 200:
            raise RuntimeError(f"Failed to observe model parameters: {model_info_resp.text}")

        model_card = model_info_resp.json()
        props = props_resp.json() if props_resp.status_code == 200 else {}
        params = model_card.get("parameters", {})

        effective = EffectiveParameters(
            model_name=model_card.get("id", profile.model_name),
            backend=BackendType(params.get("backend", profile.backend)),
            max_seq_len=int(params.get("max_seq_len", profile.max_seq_len)),
            cache_size=int(params.get("cache_size", profile.cache_size)),
            cache_mode=normalize_cache_mode(str(params.get("cache_mode", profile.cache_mode))),
            max_batch_size=int(params.get("max_batch_size", profile.max_batch_size)),
            chunk_size=int(params.get("chunk_size", profile.chunk_size)),
            use_vision=bool(params.get("use_vision", profile.use_vision)),
            draft_enabled=bool(params.get("draft_enabled", False)),
        )

        # Validate effective parameters match load profile
        if effective.max_seq_len != profile.max_seq_len:
            raise ValueError(f"Effective context mismatch: {effective.max_seq_len} != {profile.max_seq_len}")
        if effective.cache_mode != profile.cache_mode:
            raise ValueError(f"Effective cache_mode mismatch: {effective.cache_mode} != {profile.cache_mode}")

        self._active_profile = profile
        self._effective_params = effective
        return effective

    async def unload_model(self) -> None:
        """Invokes /v1/model/unload and verifies model removal."""
        resp = await self._client.post("/v1/model/unload")
        if resp.status_code != 200:
            raise RuntimeError(f"Model unload failed: {resp.status_code} - {resp.text}")

        self._active_profile = None
        self._effective_params = None

    async def close(self) -> None:
        await self._client.aclose()
