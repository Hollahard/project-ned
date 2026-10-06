"""Tests for dead inference server handling."""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
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


class DeadInferenceBackend(InferenceBackend):
    """Simulates an unreachable or crashed TabbyAPI process."""

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=False, state=ModelState.ERROR, details="Connection refused: 127.0.0.1:5000")

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def load_model(self, profile: ModelProfile) -> None:
        raise ConnectionError("Cannot reach inference server")

    async def unload_model(self) -> None:
        pass

    async def generate(self, request: ChatRequest):
        # Emits an ERROR event immediately without raising unhandled exceptions
        yield InferenceEvent(
            type=InferenceEventType.ERROR,
            content="Inference backend connection refused: http://127.0.0.1:5000",
        )


@pytest.fixture
def dead_app_client(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
    )
    dead_backend = DeadInferenceBackend()
    app = create_app(config=config, inference=dead_backend)
    with TestClient(app) as client:
        yield client


def test_dead_inference_via_rest(dead_app_client):
    # 1. Create session
    resp = dead_app_client.post("/api/v1/sessions", json={"title": "Dead Inference Test"})
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # 2. Run turn via REST
    turn_resp = dead_app_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"prompt": "Hello?"},
    )
    assert turn_resp.status_code == 200
    data = turn_resp.json()
    events = data["events"]
    event_types = [e["type"] for e in events]
    assert "error" in event_types
    # Server did not crash!


def test_dead_inference_via_websocket(dead_app_client):
    resp = dead_app_client.post("/api/v1/sessions", json={"title": "Dead Inference WS Test"})
    session_id = resp.json()["id"]

    with dead_app_client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.send_json({"type": "turn.submit", "prompt": "Hello?"})

        event1 = ws.receive_json()
        assert event1["type"] == "turn.started"

        event2 = ws.receive_json()
        assert event2["type"] == "error"
        assert "Inference backend connection refused" in event2["payload"]["error"]
