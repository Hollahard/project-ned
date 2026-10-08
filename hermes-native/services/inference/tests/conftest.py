"""Synthetic wire fixtures: no sockets, subprocesses, model files, or CUDA."""

import json
import secrets
from dataclasses import replace

import httpx
import pytest

from hermes_inference import Credentials, InMemoryAdmissionGate, LoadProfile, TabbyV3Control


def progress(status="finished", component="model", module=1, modules=1):
    return {"model_type": component, "module": module, "modules": modules, "status": status}


def sse(*values):
    return b"".join(b"data: " + json.dumps(value).encode() + b"\n\n" for value in values)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, release=None, started=None, error=None):
        self.chunks, self.release, self.started, self.error = chunks, release, started, error
        self.closed = False

    async def __aiter__(self):
        if self.started:
            self.started.set()
        if self.release:
            await self.release.wait()
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


class SyntheticTabby:
    def __init__(self, credentials):
        self.credentials = credentials
        self.loaded = None
        self.requests = []
        self.load_status = 200
        self.unload_status = 200
        self.load_body = sse(progress())
        self.load_content_type = "text/event-stream"
        self.stream_factory = None
        self.parameters_override = {}
        self.props_override = {}
        self.card_id_override = None
        self.load_applies = True
        self.unload_applies = True
        self.on_request = None
        self.auth_valid = []

    def card(self):
        p = self.loaded
        return {
            "id": self.card_id_override or p["model_name"].rsplit("/", 1)[-1],
            "parameters": {
                "max_seq_len": p["max_seq_len"],
                "cache_size": p["cache_size"],
                "cache_mode": p["cache_mode"],
                "max_batch_size": p["max_batch_size"],
                "chunk_size": p["chunk_size"],
                "use_vision": p["vision"],
                "draft": None,
                "hermes_native_draft_enabled": False,
                **self.parameters_override,
            },
        }

    def props(self):
        p = self.loaded
        return {
            "model_path": "G:\\models\\" + p["model_name"].replace("/", "\\"),
            "default_generation_settings": {"n_ctx": p["max_seq_len"]},
            "total_slots": p["max_batch_size"],
            "modalities": {"vision": p["vision"]},
            **self.props_override,
        }

    async def __call__(self, request):
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, payload))
        expected = (
            self.credentials.admin_key
            if request.method == "POST"
            else self.credentials.inference_key
        )
        self.auth_valid.append(request.headers.get("Authorization") == f"Bearer {expected}")
        if self.on_request:
            await self.on_request(request)
        if path in {"/v1/model", "/props"}:
            if self.loaded is None:
                return httpx.Response(503, json={"detail": "No models are currently loaded."})
            return httpx.Response(200, json=self.card() if path == "/v1/model" else self.props())
        if path == "/v1/model/load":
            if self.load_applies and self.load_status == 200:
                self.loaded = payload
            stream = self.stream_factory() if self.stream_factory else ChunkStream([self.load_body])
            return httpx.Response(
                self.load_status, stream=stream, headers={"content-type": self.load_content_type}
            )
        if path == "/v1/model/unload":
            if self.unload_applies and self.unload_status == 200:
                self.loaded = None
            return httpx.Response(self.unload_status, json=None)
        raise AssertionError("unexpected synthetic endpoint")


@pytest.fixture
def profile():
    return LoadProfile(
        artifact_id="synthetic-artifact-a",
        revision="revision-1",
        model_name="model-a",
        expected_model_path=r"G:\models\model-a",
        cache_mode="q6",
    )


@pytest.fixture
def credentials():
    return Credentials(secrets.token_hex(16), secrets.token_hex(16))


@pytest.fixture
def gate():
    value = InMemoryAdmissionGate()
    value.open(expected_generation=0)
    return value


@pytest.fixture
def engine(credentials):
    return SyntheticTabby(credentials)


@pytest.fixture
async def control(engine, credentials, gate):
    value = TabbyV3Control(
        base_url="http://127.0.0.1:5000",
        credentials=credentials,
        gate=gate,
        transport=httpx.MockTransport(engine),
        operation_timeout=2,
    )
    yield value
    await value.aclose()


@pytest.fixture
def second_profile(profile):
    return replace(
        profile,
        artifact_id="synthetic-artifact-b",
        model_name="model-b",
        expected_model_path=r"G:\models\model-b",
    )
