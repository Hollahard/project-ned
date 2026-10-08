"""Bounded backend startup proof; no renderer or inference engine integration."""

from .readiness import ReadinessError, ReadinessParser

__all__ = ["ReadinessError", "ReadinessParser"]
