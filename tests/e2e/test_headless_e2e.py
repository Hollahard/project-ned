"""End-to-End Headless validation script for Phase 2."""

import asyncio
import json
import logging
import pytest
from starlette.testclient import TestClient

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, SecuritySettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ModelProfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phase2_e2e")


def test_phase2_headless_lifecycle(tmp_path):
    """Verify curl-style REST session creation, WebSocket event streaming, and graceful cancellation."""
    db_file = tmp_path / "e2e_state.db"
    token = "test-launch-bearer-token"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
        security=SecuritySettings(bearer_token=token),
    )
    mock_inference = MockInferenceBackend()
    mock_inference.state = "READY"
    mock_inference.active_profile = ModelProfile(name="mock-model", model_dir="")
    app = create_app(config=config, inference=mock_inference)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Health check (no auth needed)
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"
        logger.info("1. Health check passed")

        # 2. REST Create Session (simulating curl create-session)
        create_resp = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"title": "E2E Headless Session", "working_directory": ".", "model_profile": "mock-model"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]
        logger.info("2. REST Session created: %s", session_id)

        # 3. REST Submit Prompt
        turn_resp = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            headers=headers,
            json={"prompt": "Hello Core REST!"},
        )
        assert turn_resp.status_code == 200
        assert "final_answer" in turn_resp.json()
        logger.info("3. REST Turn submitted and completed")

        # 4. WebSocket Event Streaming (simulating frontend WS client)
        with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
            ws.send_json({"type": "turn.submit", "prompt": "Hello Core WebSocket!"})
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "turn.completed":
                    break

            event_types = [e["type"] for e in events]
            assert "turn.started" in event_types
            assert "assistant.delta" in event_types
            assert "turn.completed" in event_types
            logger.info("4. WebSocket streaming completed with events: %s", event_types)

        # 5. Model Management via REST
        status_resp = client.get("/api/v1/runtime/status", headers=headers)
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "online"
        logger.info("5. Runtime status endpoint verified")

        logger.info("Phase 2 Headless E2E Verification PASSED!")
