"""Tests for GPU telemetry provider and NVML metrics."""

from pathlib import Path
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.telemetry import TelemetryProvider, GpuTelemetry


def test_telemetry_provider_live_or_fallback():
    provider = TelemetryProvider(device_index=0)
    telemetry = provider.get_gpu_telemetry()
    assert isinstance(telemetry, GpuTelemetry)
    if telemetry.available:
        assert "RTX" in telemetry.device_name or "GeForce" in telemetry.device_name or "NVIDIA" in telemetry.device_name
        assert telemetry.vram_total_mb > 0
        assert telemetry.vram_used_mb >= 0
        assert telemetry.vram_free_mb > 0
        assert 0.0 <= telemetry.vram_usage_percent <= 100.0
        assert telemetry.temperature_c >= 0
        assert telemetry.power_watts >= 0.0
    else:
        assert telemetry.device_name != ""


def test_telemetry_provider_mock_nvml_unavailable():
    provider = TelemetryProvider(device_index=0)
    provider._nvml_initialized = False

    with patch.object(provider, "_init_nvml"):
        telemetry = provider.get_gpu_telemetry()
        assert not telemetry.available
        assert "No NVML Device Available" in telemetry.device_name


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
async def test_telemetry_gpu_endpoint(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.get("/api/v1/telemetry/gpu")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "device_name" in data
        assert "vram_total_mb" in data
        assert "vram_used_mb" in data
