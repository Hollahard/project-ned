"""Pure profile schema with lazy HTTP control exports.

CPU-only profile consumers do not need httpx or a configured inference runtime.
The existing public control API resolves on first access when its dependencies
are available; import failures remain visible to the requesting caller.
"""

from importlib import import_module
from typing import TYPE_CHECKING

from .admission import AdmissionGate, AdmissionSnapshot, InMemoryAdmissionGate
from .profiles import LoadProfile, normalize_cache_mode

if TYPE_CHECKING:
    from .control import (
        MANAGED_CONTRACT_VERSION,
        RUNTIME_PACK_ID,
        TABBY_V3_COMMIT,
        ControlState,
        ControlStatus,
        Credentials,
        GenerationLease,
        TabbyV3Control,
    )
    from .sse import StreamLimits

_CONTROL_EXPORTS = frozenset(
    {
        "MANAGED_CONTRACT_VERSION",
        "RUNTIME_PACK_ID",
        "TABBY_V3_COMMIT",
        "ControlState",
        "ControlStatus",
        "Credentials",
        "GenerationLease",
        "TabbyV3Control",
    }
)


def __getattr__(name: str):
    if name in _CONTROL_EXPORTS:
        module = ".control"
    elif name == "StreamLimits":
        module = ".sse"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "AdmissionGate",
    "AdmissionSnapshot",
    "InMemoryAdmissionGate",
    "ControlState",
    "ControlStatus",
    "Credentials",
    "GenerationLease",
    "RUNTIME_PACK_ID",
    "MANAGED_CONTRACT_VERSION",
    "TABBY_V3_COMMIT",
    "TabbyV3Control",
    "LoadProfile",
    "normalize_cache_mode",
    "StreamLimits",
]
