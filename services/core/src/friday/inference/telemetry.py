"""Hardware telemetry provider using NVML for Project Friday (RTX 5090 Blackwell)."""

import logging
from typing import Any, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class GpuTelemetry(BaseModel):
    available: bool = False
    device_name: str = "Unknown"
    driver_version: str = "Unknown"
    nvml_version: str = "Unknown"
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    vram_usage_percent: float = 0.0
    temperature_c: int = 0
    power_watts: float = 0.0
    power_limit_watts: float = 0.0
    utilization_gpu_percent: int = 0
    utilization_mem_percent: int = 0


class TelemetryProvider:
    """Queries NVIDIA GPU telemetry via NVML with graceful fallback."""

    def __init__(self, device_index: int = 0) -> None:
        self.device_index = device_index
        self._nvml_initialized = False
        self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml_initialized = True
            logger.info("NVML initialized successfully on device index %d", self.device_index)
        except Exception as exc:
            self._nvml_initialized = False
            logger.debug("NVML not available or initialization failed: %s", exc)

    def get_gpu_telemetry(self) -> GpuTelemetry:
        """Fetch current snapshot of GPU telemetry."""
        if not self._nvml_initialized:
            # Re-try init once in case driver became available
            self._init_nvml()

        if not self._nvml_initialized:
            return GpuTelemetry(available=False, device_name="No NVML Device Available")

        try:
            import pynvml
            handle = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
            name = pynvml.nvmlDeviceGetName(handle)
            driver = pynvml.nvmlSystemGetDriverVersion()
            nvml_ver = pynvml.nvmlSystemGetNVMLVersion()

            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_mb = round(mem_info.total / (1024**2), 1)
            used_mb = round(mem_info.used / (1024**2), 1)
            free_mb = round(mem_info.free / (1024**2), 1)
            usage_pct = round((mem_info.used / mem_info.total) * 100, 1) if mem_info.total > 0 else 0.0

            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
            power_w = round(power_mw / 1000.0, 1)

            try:
                power_limit_mw = pynvml.nvmlDeviceGetPowerManagementLimit(handle)
                power_limit_w = round(power_limit_mw / 1000.0, 1)
            except Exception:
                power_limit_w = 0.0

            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util = util.gpu
                mem_util = util.memory
            except Exception:
                gpu_util = 0
                mem_util = 0

            return GpuTelemetry(
                available=True,
                device_name=str(name),
                driver_version=str(driver),
                nvml_version=str(nvml_ver),
                vram_total_mb=total_mb,
                vram_used_mb=used_mb,
                vram_free_mb=free_mb,
                vram_usage_percent=usage_pct,
                temperature_c=temp,
                power_watts=power_w,
                power_limit_watts=power_limit_w,
                utilization_gpu_percent=gpu_util,
                utilization_mem_percent=mem_util,
            )
        except Exception as exc:
            logger.warning("Error fetching NVML telemetry: %s", exc)
            return GpuTelemetry(available=False, device_name=f"NVML Error: {exc}")

    def close(self) -> None:
        if self._nvml_initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False
