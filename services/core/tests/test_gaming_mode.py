"""Tests for Gaming Mode instant generation abort and VRAM evacuation."""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ModelState
from friday.inference.gaming_mode import GamingModeController, GamingModeStatus


@pytest.mark.asyncio
async def test_gaming_mode_controller_evacuation():
    backend = MockInferenceBackend()
    controller = GamingModeController()

    # Load mock model first
    from friday.inference.protocol import ModelProfile
    await backend.load_model(ModelProfile(name="mock-model", model_dir=""))
    health = await backend.health()
    assert health.state == ModelState.READY

    # Activate Gaming Mode
    status = await controller.activate(backend=backend)
    assert isinstance(status, GamingModeStatus)
    assert status.active is True
    # Invariant: evacuation executes in < 2.0s
    assert status.elapsed_seconds < 2.0
    assert "Gaming Mode ACTIVE" in status.message

    # Backend model must be unloaded
    health_after = await backend.health()
    assert health_after.state == ModelState.UNLOADED

    # Deactivate Gaming Mode
    deact_status = await controller.deactivate()
    assert deact_status.active is False
    assert controller.active is False


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
async def test_gaming_mode_api_workflow_and_invariants(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        # 1. Create a session
        sess_resp = await client.post("/api/v1/sessions", json={"title": "Gaming Mode Test"})
        assert sess_resp.status_code == 201
        session_id = sess_resp.json()["id"]

        # 2. Check initial gaming mode status
        gm_status = await client.get("/api/v1/gaming-mode/status")
        assert gm_status.status_code == 200
        assert gm_status.json()["active"] is False

        # 3. Activate Gaming Mode
        act_resp = await client.post("/api/v1/gaming-mode/activate")
        assert act_resp.status_code == 200
        act_data = act_resp.json()
        assert act_data["active"] is True
        assert act_data["elapsed_seconds"] < 2.0

        # Verify runtime status reflects gaming mode
        rt_resp = await client.get("/api/v1/runtime/status")
        assert rt_resp.status_code == 200
        assert rt_resp.json()["gaming_mode"]["active"] is True

        # 4. Invariant: When Gaming Mode is active, new model loads MUST be blocked (HTTP 409)
        load_blocked = await client.post(
            "/api/v1/models/load",
            json={"name": "test-model"},
        )
        assert load_blocked.status_code == 409
        assert "Gaming Mode is active" in load_blocked.json()["detail"]

        # 5. Invariant: When Gaming Mode is active, new turns MUST be blocked (HTTP 409)
        turn_blocked = await client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"prompt": "Hello Friday"},
        )
        assert turn_blocked.status_code == 409
        assert "Gaming Mode is active" in turn_blocked.json()["detail"]

        # 6. Deactivate Gaming Mode
        deact_resp = await client.post("/api/v1/gaming-mode/deactivate")
        assert deact_resp.status_code == 200
        assert deact_resp.json()["active"] is False

        # 7. Model loading and turns unblocked
        load_ok = await client.post(
            "/api/v1/models/load",
            json={"name": "test-model"},
        )
        assert load_ok.status_code == 200
