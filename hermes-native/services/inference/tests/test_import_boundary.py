"""Profile-only clients use the real public package without HTTP dependencies."""

import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_public_profile_import_without_site_packages(tmp_path):
    code = """
import json,sys
sys.path.insert(0,sys.argv[1])
from hermes_inference import LoadProfile, AdmissionSnapshot, InMemoryAdmissionGate
value=LoadProfile('artifact','revision','model',r'C:\\models\\model',cache_mode='q4')
assert value.cache_mode == '4,4'
assert InMemoryAdmissionGate().snapshot() == AdmissionSnapshot(0,False)
assert not any(name in sys.modules for name in ('httpx','torch','triton','exllamav3'))
import hermes_inference
assert 'TabbyV3Control' in dir(hermes_inference)
try:
    hermes_inference.TabbyV3Control
except ModuleNotFoundError as error:
    assert error.name == 'httpx'
else:
    raise AssertionError('HTTP dependency must remain absent in no-site interpreter')
print(json.dumps({'schema_import':'passed'}))
"""
    environment = {
        name: os.environ[name] for name in ("SystemRoot", "WINDIR") if name in os.environ
    }
    result = subprocess.run(
        [sys._base_executable, "-I", "-S", "-B", "-X", "utf8", "-c", code, str(SOURCE)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=15,
        check=True,
    )
    assert json.loads(result.stdout) == {"schema_import": "passed"}


def test_existing_control_exports_remain_identical():
    import hermes_inference
    from hermes_inference.control import Credentials, TabbyV3Control
    from hermes_inference.sse import StreamLimits

    assert hermes_inference.Credentials is Credentials
    assert hermes_inference.TabbyV3Control is TabbyV3Control
    assert hermes_inference.StreamLimits is StreamLimits
    assert hermes_inference.TabbyV3Control is hermes_inference.TabbyV3Control


def test_unknown_public_export_is_attribute_error():
    import pytest

    import hermes_inference

    with pytest.raises(AttributeError):
        _ = hermes_inference.does_not_exist
