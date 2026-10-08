import os
import sys
from pathlib import Path

import pytest

source = Path(os.environ["HERMES_CONTROL_INFERENCE_SRC"]).resolve(strict=True)
sys.path.insert(0, str(source))


@pytest.fixture
def profile():
    return {
        "artifact_id": "test-artifact",
        "revision": "test-bytes-revision",
        "model_name": "test-model",
        "expected_model_path": "C:/models/test-model",
        "context_length": 2048,
        "cache_size": 2048,
        "cache_mode": "q4",
        "chunk_size": 256,
    }
