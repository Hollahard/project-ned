import ast
import hashlib
import json

import pytest

import build_overlay as builder


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "common").mkdir(parents=True)
    values = {
        "common/auth.py": b"# original placeholder auth\n",
        "common/networking.py": b"""# retained prefix
async def log_request(request: Request):
    xlogger.info(dict(request))

def get_global_depends():
    return []
""",
        "endpoints/core/types/model.py": b"""class ModelCardParameters:
    draft: Optional["ModelCard"] = None
""",
        "backends/exllamav3/model.py": b"""class ExllamaV3Container:
    def model_info(self):
        return ModelCardParameters(
            use_vision=self.use_vision,
        )
""",
        "LICENSE": b"fixture license\n",
    }
    for relative, value in values.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(value)
    monkeypatch.setattr(
        builder,
        "SOURCE_HASHES",
        {key: hashlib.sha256(value).hexdigest() for key, value in values.items()},
    )
    return root


def test_overlay_preserves_source_and_other_networking_functions(source, tmp_path):
    original = {
        relative: (source / relative).read_bytes() for relative in builder.SOURCE_HASHES
    }
    output = tmp_path / "fresh-output"
    manifest = builder.build_overlay(source, output)
    assert original == {
        relative: (source / relative).read_bytes() for relative in original
    }
    assert json.loads((output / "overlay-manifest.json").read_text()) == manifest
    network = (output / "common/networking.py").read_text()
    assert network.startswith("# retained prefix\n")
    assert "def get_global_depends():\n    return []" in network
    ast.parse(network)
    assert (output / "UPSTREAM-LICENSE.txt").read_bytes() == original["LICENSE"]
    assert manifest["managed_contract_version"] == "hermes-native-observation-v1"
    assert manifest["runtime_pack_id"] == builder.RUNTIME_PACK_ID
    assert manifest["effective_observation_fields"] == [
        "parameters.hermes_native_draft_enabled"
    ]
    assert (
        "hermes_native_draft_enabled: Optional[bool] = None"
        in (output / "endpoints/core/types/model.py").read_text()
    )
    assert (
        "bool(self.use_draft_model or self.ngram_match_min > 0)"
        in (output / "backends/exllamav3/model.py").read_text()
    )
    for relative, digest in manifest["overlay_sha256"].items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("relative", list(builder.SOURCE_HASHES))
def test_changed_upstream_rejected_before_output_write(source, tmp_path, relative):
    (source / relative).write_text("# drift\n")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Pinned upstream file changed"):
        builder.build_overlay(source, output)
    assert not output.exists()


@pytest.mark.parametrize("backend", [False, True])
def test_missing_or_duplicate_observation_anchor_fails_closed(backend):
    with pytest.raises(ValueError, match="insertion point"):
        builder.add_observation_field(b"# no matching declaration\n", backend=backend)
    anchor = (
        b"            use_vision=self.use_vision,\n"
        if backend
        else b'    draft: Optional["ModelCard"] = None\n'
    )
    with pytest.raises(ValueError, match="insertion point"):
        builder.add_observation_field(anchor * 2, backend=backend)


@pytest.mark.parametrize("relative", ["source", "source/output", "."])
def test_existing_or_source_nested_destination_rejected(source, tmp_path, relative):
    with pytest.raises(ValueError, match="new directory outside"):
        builder.build_overlay(source, tmp_path / relative)


def test_existing_output_never_overwritten(source, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "preserve.txt"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError):
        builder.build_overlay(source, output)
    assert sentinel.read_text() == "preserve"
