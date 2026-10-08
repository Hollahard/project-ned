"""Emit only fixed Boolean diagnostics, never environment values or arbitrary names."""

import json
import os
import sys
from pathlib import Path

known = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUTF8",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
    "PYTHONNOUSERSITE",
    "PYTHONSAFEPATH",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONLEGACYWINDOWSSTDIO",
    "PYTHONUSERBASE",
)
result = {name.lower() + "_present": name in os.environ for name in known}
result["other_python_environment_count"] = sum(
    name.startswith("PYTHON") and name not in known for name in os.environ
)
result["tabby_environment_count"] = sum(name.startswith("TABBY_") for name in os.environ)
result["isolated"] = bool(sys.flags.isolated)
result["no_site"] = bool(sys.flags.no_site)
result["no_bytecode"] = sys.dont_write_bytecode
result["pythonhome_matches_base_prefix"] = (
    Path(os.environ.get("PYTHONHOME", "")).resolve() == Path(sys.base_prefix).resolve()
)
Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
