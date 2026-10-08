"""Pinned V3 control contract. No CUDA imports, GPU probes, or autonomous launches."""

import asyncio
import ipaddress
import json
import logging
import math
import ntpath
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

from .admission import AdmissionGate, AdmissionSnapshot, require_admission
from .errors import (
    EffectiveSettingsMismatch,
    IdentityMismatch,
    InferenceControlError,
    OperationUncertain,
    ProfileValidationError,
    ProtocolError,
    RemoteOperationError,
    UnsupportedManagedRuntime,
)
from .profiles import LoadProfile, canonical_model_path, normalize_observed_cache_mode
from .sse import StreamLimits, events, validate_progress

logger = logging.getLogger(__name__)
TABBY_V3_COMMIT = "2fd6cc76203a66e13042daf7d76e5898b21c1ad8"
MANAGED_CONTRACT_VERSION = "hermes-native-observation-v1"
RUNTIME_PACK_ID = f"tabby-v3:{TABBY_V3_COMMIT}:{MANAGED_CONTRACT_VERSION}"


@dataclass(frozen=True, slots=True)
class Credentials:
    inference_key: str = field(repr=False)
    admin_key: str = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.inference_key, self.admin_key):
            if (
                not isinstance(value, str)
                or not value
                or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            ):
                raise ValueError("nonempty credentials without whitespace are required")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        inference_var: str = "HERMES_TABBY_API_KEY",
        admin_var: str = "HERMES_TABBY_ADMIN_KEY",
    ) -> "Credentials":
        environment = os.environ if environ is None else environ
        return cls(environment.get(inference_var, ""), environment.get(admin_var, ""))


class ControlState(StrEnum):
    UNKNOWN = "unknown"
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    UNLOADING = "unloading"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ControlStatus:
    state: ControlState
    active_profile: LoadProfile | None
    runtime_generation: int
    error_code: str | None


@dataclass(frozen=True, slots=True)
class GenerationLease:
    profile: LoadProfile
    runtime_pack_id: str
    runtime_generation: int
    admission: AdmissionSnapshot
    _gate: AdmissionGate = field(repr=False)
    _valid: bool = field(default=True, repr=False)

    def ensure_valid(self) -> None:
        """Check before forwarding each generation request/chunk or subsequent tool round."""
        if not self._valid:
            raise OperationUncertain("generation lease has expired")
        require_admission(self._gate, self.admission)


class TabbyV3Control:
    """One owned runtime, one event loop, one generation/transition at a time.

    The caller must establish exclusive runtime ownership and verify pack/artifact
    integrity outside this adapter. HTTP identity cannot prove file hashes or commit.
    """

    def __init__(
        self,
        *,
        base_url: str,
        credentials: Credentials,
        gate: AdmissionGate,
        transport: httpx.AsyncBaseTransport | None = None,
        operation_timeout: float = 300.0,
        stream_limits: StreamLimits | None = None,
        max_json_bytes: int = 512 * 1024,
    ) -> None:
        url = httpx.URL(base_url)
        try:
            loopback = ipaddress.ip_address(url.host).is_loopback
        except ValueError:
            loopback = False
        if (
            not loopback
            or url.scheme not in {"http", "https"}
            or url.userinfo
            or url.query
            or url.fragment
            or url.path != "/"
        ):
            raise ValueError("base_url must be a credential-free numeric loopback origin")
        if (
            not math.isfinite(operation_timeout)
            or operation_timeout <= 0
            or type(max_json_bytes) is not int
            or max_json_bytes <= 0
        ):
            raise ValueError("operation and response limits must be positive")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self._credentials = credentials
        self._gate = gate
        self._lock = asyncio.Lock()
        self._timeout = operation_timeout
        self._limits = stream_limits or StreamLimits()
        self._max_json_bytes = max_json_bytes
        self._state = ControlState.UNKNOWN
        self._active: LoadProfile | None = None
        self._pending: LoadProfile | None = None
        self._generation = 0
        self._error_code: str | None = None

    def status(self) -> ControlStatus:
        return ControlStatus(self._state, self._active, self._generation, self._error_code)

    async def aclose(self) -> None:
        """Close HTTP handles only. Does not unload or terminate the external runtime."""
        async with self._lock:
            await self._client.aclose()

    def _headers(self, *, admin: bool = False) -> dict[str, str]:
        key = self._credentials.admin_key if admin else self._credentials.inference_key
        return {"Authorization": f"Bearer {key}"}

    def _uncertain(self, code: str) -> None:
        self._state, self._active, self._error_code = ControlState.UNCERTAIN, None, code
        self._generation += 1
        logger.error("Inference control state uncertain: %s", code)

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(self._timeout):
                yield
        except asyncio.CancelledError:
            self._uncertain("OPERATION_CANCELLED")
            raise
        except (httpx.HTTPError, TimeoutError):
            self._uncertain("OPERATION_UNCERTAIN")
            raise OperationUncertain(
                "engine observation interrupted; reconcile before retry"
            ) from None
        except InferenceControlError as exc:
            self._uncertain(exc.code)
            raise
        except Exception:
            self._uncertain("CONTROL_OPERATION_INTERRUPTED")
            raise OperationUncertain(
                "control operation failed before engine state was verified"
            ) from None

    async def _json(self, path: str, *, absent_ok: bool = False) -> dict | None:
        async with self._client.stream("GET", path, headers=self._headers()) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > self._max_json_bytes:
                    raise ProtocolError("engine JSON response exceeds byte limit")
            try:
                value = json.loads(raw)
            except (ValueError, RecursionError):
                raise ProtocolError("engine returned malformed JSON") from None
            if not isinstance(value, dict):
                raise ProtocolError("engine JSON response must be an object")
            if (
                absent_ok
                and response.status_code == 503
                and value.get("detail") == "No models are currently loaded."
            ):
                return None
            if response.status_code != 200:
                raise RemoteOperationError(
                    f"engine observation failed with HTTP {response.status_code}"
                )
            return value

    async def _observe(self) -> tuple[dict, dict] | None:
        card = await self._json("/v1/model", absent_ok=True)
        if card is None:
            return None
        props = await self._json("/props")
        # A second card catches a model switch between the two endpoint observations.
        second = await self._json("/v1/model", absent_ok=True)
        if second is None or any(card.get(k) != second.get(k) for k in ("id", "parameters")):
            raise IdentityMismatch("engine identity changed during observation")
        return card, props

    @staticmethod
    def _verify(profile: LoadProfile, observed: tuple[dict, dict] | None) -> None:
        if observed is None:
            raise IdentityMismatch("expected model is not loaded")
        card, props = observed
        try:
            actual_path = canonical_model_path(props.get("model_path"))
        except ProfileValidationError:
            raise ProtocolError("engine did not report an absolute model path") from None
        reported_id = card.get("id")
        if isinstance(reported_id, str) and ntpath.splitdrive(profile.expected_model_path)[0]:
            reported_id = ntpath.normcase(reported_id)
        # Tabby resolves the load alias first and reports the resolved directory's name.
        # Keep the exact absolute path check: unrelated quant directories can share a basename.
        if actual_path != profile.expected_model_path or reported_id != ntpath.basename(
            profile.expected_model_path
        ):
            raise IdentityMismatch("actual engine artifact differs from requested profile")
        parameters = card.get("parameters")
        generation = props.get("default_generation_settings")
        modalities = props.get("modalities")
        if (
            not isinstance(parameters, dict)
            or not isinstance(generation, dict)
            or not isinstance(modalities, dict)
        ):
            raise ProtocolError("engine did not report effective settings")
        draft_enabled = parameters.get("hermes_native_draft_enabled")
        if type(draft_enabled) is not bool:
            raise UnsupportedManagedRuntime(
                "managed draft-state observation is required; stock Tabby is unsupported"
            )
        if draft_enabled or parameters.get("draft") is not None:
            raise EffectiveSettingsMismatch("unverified drafting remains enabled")
        expected = {
            "max_seq_len": profile.context_length,
            "cache_size": profile.cache_size,
            "max_batch_size": profile.max_batch_size,
            "chunk_size": profile.chunk_size,
            "use_vision": profile.vision,
        }
        for key, value in expected.items():
            actual = parameters.get(key)
            if type(actual) is not type(value) or actual != value:
                raise EffectiveSettingsMismatch(f"engine did not apply {key}")
        try:
            cache_mode = normalize_observed_cache_mode(parameters.get("cache_mode"))
        except ProfileValidationError:
            raise ProtocolError("engine returned an unsupported cache precision") from None
        if cache_mode != profile.cache_mode:
            raise EffectiveSettingsMismatch("engine did not apply cache_mode")
        for actual, expected_value, field_name in (
            (generation.get("n_ctx"), profile.context_length, "n_ctx"),
            (props.get("total_slots"), profile.max_batch_size, "total_slots"),
            (modalities.get("vision"), profile.vision, "vision"),
        ):
            if type(actual) is not type(expected_value) or actual != expected_value:
                raise EffectiveSettingsMismatch(f"engine props disagree on {field_name}")

    async def _unload(self) -> None:
        self._state = ControlState.UNLOADING
        async with self._client.stream(
            "POST", "/v1/model/unload", headers=self._headers(admin=True)
        ) as response:
            if response.status_code != 200:
                raise RemoteOperationError(f"engine unload failed with HTTP {response.status_code}")
        if await self._json("/v1/model", absent_ok=True) is not None:
            raise IdentityMismatch("engine still reports a loaded model after unload")
        self._active, self._state = None, ControlState.UNLOADED
        self._generation += 1

    async def _load(self, profile: LoadProfile, admission: AdmissionSnapshot) -> None:
        self._state = ControlState.LOADING
        finished = False
        phases: dict[str, tuple[int, int, str]] = {}
        async with self._client.stream(
            "POST",
            "/v1/model/load",
            json=profile.payload(),
            headers=self._headers(admin=True),
        ) as response:
            if response.status_code != 200:
                raise RemoteOperationError(f"engine load failed with HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "text/event-stream":
                raise ProtocolError("load response must be an SSE stream")
            async for event in events(response, self._limits):
                require_admission(self._gate, admission)
                finished = validate_progress(event) or finished
                component = event["model_type"]
                if component == "draft":
                    raise EffectiveSettingsMismatch("unexpected draft component during load")
                current = (event["module"], event["modules"], event["status"])
                previous = phases.get(component)
                if previous and (
                    previous[2] == "finished"
                    or current[0] < previous[0]
                    or current[1] != previous[1]
                ):
                    raise ProtocolError("load progress changed inconsistently")
                phases[component] = current
        if not finished:
            raise ProtocolError("load stream ended without a finished main-model event")
        if any(phase[2] != "finished" for phase in phases.values()):
            raise ProtocolError("load stream ended before every observed phase finished")
        require_admission(self._gate, admission)

    async def apply(self, profile: LoadProfile) -> ControlStatus:
        admission = require_admission(self._gate)
        async with self._lock:
            require_admission(self._gate, admission)
            if self._state == ControlState.UNCERTAIN:
                raise OperationUncertain(
                    "reconcile uncertain runtime before another model transition"
                )
            self._pending = profile
            async with self._operation():
                observed = await self._observe()
                require_admission(self._gate, admission)
                if self._state == ControlState.READY and self._active == profile:
                    self._verify(profile, observed)
                    return self.status()
                if observed is not None:
                    await self._unload()
                    require_admission(self._gate, admission)
                await self._load(profile, admission)
                self._verify(profile, await self._observe())
                require_admission(self._gate, admission)
                self._active, self._state, self._error_code = profile, ControlState.READY, None
                self._generation += 1
                logger.info("Verified V3 load profile applied")
                return self.status()

    async def reconcile(self, profile: LoadProfile) -> ControlStatus:
        """Explicitly observe pending intent after loss; never start/retry a load.

        An absent model cannot clear UNCERTAIN: a detached load may still be running.
        Exclusive runtime ownership and unchanged artifact files remain prerequisites.
        """
        admission = require_admission(self._gate)
        async with self._lock:
            require_admission(self._gate, admission)
            if self._pending != profile:
                raise IdentityMismatch("reconciliation requires the pending profile identity")
            async with self._operation():
                self._verify(profile, await self._observe())
                require_admission(self._gate, admission)
                self._active, self._state, self._error_code = profile, ControlState.READY, None
                self._generation += 1
                return self.status()

    async def unload(self) -> ControlStatus:
        """Teardown allowed with closed admission. This does NOT certify VRAM release."""
        async with self._lock:
            if self._state == ControlState.UNCERTAIN:
                raise OperationUncertain(
                    "detached operation unresolved; coordinator must reconcile or retire runtime"
                )
            async with self._operation():
                if await self._observe() is not None:
                    await self._unload()
                self._state, self._active, self._pending, self._error_code = (
                    ControlState.UNLOADED,
                    None,
                    None,
                    None,
                )
                return self.status()

    @asynccontextmanager
    async def generation(self, profile: LoadProfile) -> AsyncIterator[GenerationLease]:
        """Hold for the ENTIRE generation stream; caller forwards only under this lease.

        Recheck lease.ensure_valid() before each forwarded chunk/tool round. Closing
        admission blocks new leases but does not itself cancel an arbitrary caller's
        ongoing I/O: the resource controller must cancel its owned generation tasks.
        """
        admission = require_admission(self._gate)
        async with self._lock:
            require_admission(self._gate, admission)
            if self._state != ControlState.READY or self._active != profile:
                raise IdentityMismatch(
                    "request artifact/profile is not the verified active profile"
                )
            async with self._operation():
                self._verify(profile, await self._observe())
                require_admission(self._gate, admission)
            lease = GenerationLease(
                profile, RUNTIME_PACK_ID, self._generation, admission, self._gate
            )
            try:
                yield lease
                lease.ensure_valid()
            except asyncio.CancelledError:
                self._uncertain("GENERATION_CANCELLED")
                raise
            except InferenceControlError as exc:
                self._uncertain(exc.code)
                raise
            except Exception:
                self._uncertain("GENERATION_INTERRUPTED")
                raise
            finally:
                object.__setattr__(lease, "_valid", False)
