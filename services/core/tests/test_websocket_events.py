"""Tests for WebSocket streaming events on /ws/sessions/{id}."""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ModelProfile


@pytest.fixture
def test_client(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
    )
    mock_inference = MockInferenceBackend()
    app = create_app(config=config, inference=mock_inference)
    with TestClient(app) as client:
        yield client, mock_inference


def test_websocket_stream_turn(test_client):
    client, mock_inference = test_client

    # 1. Create session via REST
    resp = client.post("/api/v1/sessions", json={"title": "WS Test"})
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # 2. Ensure model is READY
    mock_inference.state = "READY"
    mock_inference.active_profile = ModelProfile(name="mock", model_dir="")

    # 3. Connect via WebSocket
    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        # Submit turn
        ws.send_json({"type": "turn.submit", "prompt": "Hello via WebSocket!"})

        # Collect events until turn.completed
        received_types = []
        for _ in range(20):
            event = ws.receive_json()
            received_types.append(event["type"])
            assert "event_id" in event
            assert "timestamp" in event
            assert event["session_id"] == session_id
            if event["type"] == "turn.completed":
                break

        assert "turn.started" in received_types
        assert "assistant.delta" in received_types
        assert "turn.completed" in received_types


def test_websocket_invalid_session(test_client):
    client, _ = test_client
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/sessions/nonexistent-session-id-123"):
            pass
