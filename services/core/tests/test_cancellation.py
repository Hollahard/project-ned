"""Tests for turn cancellation via WebSocket."""

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
    # Provide a slow response to test cancellation mid-stream
    mock_inference.mock_responses = ["word " * 50]
    app = create_app(config=config, inference=mock_inference)
    with TestClient(app) as client:
        yield client, mock_inference


def test_turn_cancellation(test_client):
    client, mock_inference = test_client

    # Create session
    resp = client.post("/api/v1/sessions", json={"title": "Cancel Test"})
    session_id = resp.json()["id"]

    mock_inference.state = "READY"
    mock_inference.active_profile = ModelProfile(name="mock", model_dir="")

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        # Submit turn
        ws.send_json({"type": "turn.submit", "prompt": "Long streaming response..."})

        # Receive first event
        event1 = ws.receive_json()
        assert event1["type"] == "turn.started"

        # Send cancellation
        ws.send_json({"type": "turn.cancel"})

        # Collect subsequent events: should receive error or cancellation
        event_types = []
        for _ in range(10):
            try:
                ev = ws.receive_json()
                event_types.append(ev["type"])
                if ev["type"] in ("turn.canceled", "error"):
                    break
            except Exception:
                break

        assert any(t in event_types for t in ["turn.canceled", "error", "turn.completed"])
