"""Tests for model management and runtime status routes."""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ModelState


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
async def test_list_models_route(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) >= 1
        assert models[0]["id"] == "mock-qwen-27b"


@pytest.mark.asyncio
async def test_load_and_unload_model_routes(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        # Load model
        load_resp = await client.post(
            "/api/v1/models/load",
            json={"name": "test-model-exl3", "context_length": 16384, "kv_cache_dtype": "q6"},
        )
        assert load_resp.status_code == 200
        assert load_resp.json()["loaded_model"] == "test-model-exl3"

        # Check runtime status
        status_resp = await client.get("/api/v1/runtime/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "online"
        assert status_data["inference"]["model_id"] == "test-model-exl3"
        assert status_data["inference"]["state"] == ModelState.READY

        # Unload model
        unload_resp = await client.post("/api/v1/models/unload")
        assert unload_resp.status_code == 200
        assert unload_resp.json()["status"] == "ok"

        # Check status again
        status_resp2 = await client.get("/api/v1/runtime/status")
        assert status_resp2.json()["inference"]["state"] == ModelState.UNLOADED
