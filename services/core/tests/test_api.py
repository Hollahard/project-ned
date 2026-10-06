"""Tests for Friday Core FastAPI endpoints."""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ModelProfile


@pytest.fixture
async def test_app(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
    )
    mock_inference = MockInferenceBackend()
    app = create_app(config=config, inference=mock_inference)
    yield app
    await app.state.db_manager.close()



@pytest.mark.asyncio
async def test_health_check(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "inference" in data


@pytest.mark.asyncio
async def test_session_lifecycle(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        # Create session
        create_resp = await client.post(
            "/api/v1/sessions",
            json={"title": "Test Chat", "working_directory": ".", "model_profile": "mock"},
        )
        assert create_resp.status_code == 201
        session_data = create_resp.json()
        session_id = session_data["id"]

        # Get session
        get_resp = await client.get(f"/api/v1/sessions/{session_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Test Chat"

        # List sessions
        list_resp = await client.get("/api/v1/sessions")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) >= 1

        # Delete session
        del_resp = await client.delete(f"/api/v1/sessions/{session_id}")
        assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_non_loopback_host_rejection(test_app):
    transport = ASGITransport(app=test_app)
    # Using an external Host header (e.g., example.com) must be rejected
    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8200",
        headers={"Host": "192.168.1.100:8200"},
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 403
