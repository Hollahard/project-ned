"""Pure-stdlib metadata inspection; importing this package never loads engines."""

from .catalog import InspectionReport, inspect_model
from .common import Limits

__all__ = ["InspectionReport", "Limits", "inspect_model"]
