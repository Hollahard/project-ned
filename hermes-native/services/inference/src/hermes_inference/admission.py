"""Synchronous snapshot seam for a future durable, fenced resource authority."""

from dataclasses import dataclass
from typing import Protocol

from .errors import AdmissionClosed, StaleAdmission


@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    generation: int
    allowed: bool


class AdmissionGate(Protocol):
    def snapshot(self) -> AdmissionSnapshot: ...


def require_admission(
    gate: AdmissionGate, expected: AdmissionSnapshot | None = None
) -> AdmissionSnapshot:
    current = gate.snapshot()
    if not current.allowed:
        raise AdmissionClosed("inference admission is closed")
    if expected is not None and current.generation != expected.generation:
        raise StaleAdmission("resource authority changed during the operation")
    return current


class InMemoryAdmissionGate:
    """Single event-loop test gate. Starts closed; neither durable nor cross-process."""

    def __init__(self) -> None:
        self._state = AdmissionSnapshot(generation=0, allowed=False)

    def snapshot(self) -> AdmissionSnapshot:
        return self._state

    def close(self) -> AdmissionSnapshot:
        self._state = AdmissionSnapshot(self._state.generation + 1, False)
        return self._state

    def open(self, *, expected_generation: int) -> AdmissionSnapshot:
        if self._state.generation != expected_generation:
            raise StaleAdmission("cannot open admission with a stale resource generation")
        self._state = AdmissionSnapshot(self._state.generation + 1, True)
        return self._state
