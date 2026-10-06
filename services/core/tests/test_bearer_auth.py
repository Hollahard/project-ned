"""Tests for Core per-launch bearer token authorization."""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, SecuritySettings, StorageSettings
from friday.inference.mock import MockInferenceBackend


@pytest.fixture
async def auth_app(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
        security=SecuritySettings(bearer_token="secret-per-launch-token-xyz"),
    )
    mock_inference = MockInferenceBackend()
    app = create_app(config=config, inference=mock_inference)
    yield app
    await app.state.db_manager.close()



@pytest.mark.asyncio
async def test_health_does_not_require_token(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_protected_routes_reject_missing_token(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.get("/api/v1/sessions")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_routes_accept_valid_bearer(auth_app):
    transport = ASGITransport(app=auth_app)
    headers = {"Authorization": "Bearer secret-per-launch-token-xyz"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200", headers=headers) as client:
        resp = await client.get("/api/v1/sessions")
        assert resp.status_code == 200
