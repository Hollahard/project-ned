"""Pure adapter contracts and source-loader tripwires; no model engines."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "catalog_bootstrap", ROOT / "bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def full_report():
    return {
        "model": "model",
        "status": "incomplete",
        "format": "EXL3",
        "architecture": {"declared": ["LlamaForCausalLM"]},
        "quantization": {"bits": 5},
        "shards": [],
        "observed_tensor_count": 0,
        "index_tensor_count": 1,
        "missing_shards": ["model.safetensors"],
        "metadata_fingerprint": None,
        "fingerprint_partial": True,
        "fingerprint_scope": "metadata_files_weight_headers_and_file_sizes",
        "issues": [{"code": "SHARD_MISSING", "category": "incomplete"}],
        "bytes_read": 10,
    }


def test_compact_preserves_all_missing_names_and_no_certification():
    report = full_report()
    report["missing_shards"] = [
        f"{index:02d}-" + "\u6a21" * 200 + ".safetensors" for index in range(64)
    ]
    report["issues"] *= 128
    compact = bootstrap.compact(report)
    assert compact["missing_shards"] == report["missing_shards"]
    assert len(compact["issues"]) == 32 and compact["issues_truncated"]
    assert compact["runtime_compatible"] is None
    assert compact["load_certified"] is False
    assert compact["weight_payload_bytes_read"] == 0
    assert len(json.dumps(compact, ensure_ascii=False).encode()) < 65536


def test_source_loader_hashes_compiled_bytes_and_ignores_cache(tmp_path):
    import hashlib

    package = tmp_path / "hermes_model_catalog"
    package.mkdir()
    pins = {}
    for name in bootstrap.MODULES:
        data = b"observed = 42\n"
        (package / f"{name}.py").write_bytes(data)
        pins[f"{name}.py"] = hashlib.sha256(data).hexdigest()
    (package / "catalog.pyc").write_bytes(b"poison")
    (package / "catalog.pyd").write_bytes(b"poison")
    loader = bootstrap.SourceOnly(tmp_path, pins)
    module_spec = loader.find_spec("hermes_model_catalog.catalog")
    module = importlib.util.module_from_spec(module_spec)
    (package / "catalog.py").write_bytes(b"raise RuntimeError('changed after hash')")
    loader.exec_module(module)
    assert module.observed == 42
    with pytest.raises(ValueError, match="Changed source"):
        bootstrap.SourceOnly(tmp_path, pins)
    with pytest.raises(ModuleNotFoundError):
        loader.find_spec("hermes_model_catalog.engine")


def test_preparer_rejects_output_under_grant_without_writing(tmp_path):
    grant = tmp_path / "models"
    grant.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "prepare_config.py"),
            "--python",
            str(Path(sys._base_executable).resolve()),
            "--catalog-src",
            str((ROOT / "../model-catalog/src").resolve()),
            "--working-directory",
            str(grant / "bad-cwd"),
            "--root-grant",
            str(grant),
            "--output",
            str(tmp_path / "receipt.json"),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert list(grant.iterdir()) == []
    assert not (tmp_path / "receipt.json").exists()


def test_preparer_rejects_mixed_namespace_before_writes(tmp_path):
    grant = tmp_path / "models"
    grant.mkdir()
    extended = "\\\\?\\" + str(grant / "bad-cwd")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "prepare_config.py"),
            "--python",
            str(Path(sys._base_executable).resolve()),
            "--catalog-src",
            str((ROOT / "../model-catalog/src").resolve()),
            "--working-directory",
            extended,
            "--root-grant",
            str(grant),
            "--output",
            str(tmp_path / "receipt.json"),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert list(grant.iterdir()) == []
    assert not (tmp_path / "receipt.json").exists()


def test_encoder_trims_issues_but_preserves_mandatory_unicode_names():
    report = bootstrap.compact(full_report())
    report["missing_shards"] = [
        f"{index:02d}-" + "\U0001f9e0" * 225 + ".safetensors" for index in range(64)
    ]
    report["declared_architectures"] = ["\U0001f9e0" * 128 for _ in range(8)]
    report["issues"] = [
        {"code": "SHARD_MISSING", "category": "incomplete", "file": name}
        for name in report["missing_shards"][:32]
    ]
    names = report["missing_shards"].copy()
    frame = bootstrap.encode_report(report)
    assert len(frame) <= 65536
    result = json.loads(frame)
    assert result["missing_shards"] == names
    assert result["issues_truncated"] and len(result["issues"]) < 32
    report["model"] = "x" * 65536
    with pytest.raises(ValueError, match="Output limit"):
        bootstrap.encode_report(report)


def test_actual_bootstrap_has_no_engine_network_or_subprocess_imports(tmp_path):
    import hashlib
    import struct

    root = tmp_path / "models"
    model = root / "model"
    model.mkdir(parents=True)
    (model / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["LlamaForCausalLM"],
                "quantization_config": {"quant_method": "exl3", "bits": 5},
            }
        )
    )
    header = json.dumps(
        {"layer.trellis": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}}
    ).encode()
    (model / "model.safetensors").write_bytes(
        struct.pack("<Q", len(header)) + header + b"1234"
    )
    source = (ROOT / "../model-catalog/src").resolve()
    pins = {
        f"{name}.py": hashlib.sha256(
            (source / "hermes_model_catalog" / f"{name}.py").read_bytes()
        ).hexdigest()
        for name in bootstrap.MODULES
    }
    script = """import sys,runpy
forbidden={'torch','exllamav2','exllamav3','transformers','tokenizers','httpx','requests','socket','subprocess'}
def audit(event,args):
    if event=='import' and args[0].split('.')[0] in forbidden:
        raise RuntimeError('Forbidden runtime import')
    if event.startswith(('socket.','subprocess.')):
        raise RuntimeError('Forbidden runtime action')
sys.addaudithook(audit)
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
    result = subprocess.run(
        [
            str(Path(sys._base_executable).resolve()),
            "-I",
            "-S",
            "-B",
            "-X",
            "utf8",
            "-c",
            script,
            str(ROOT / "bootstrap.py"),
            "--catalog-src",
            str(source),
            "--source-pins",
            json.dumps(pins),
            "--root",
            str(root),
            "--model=model",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["format"] == "EXL3"
    assert report["load_certified"] is False
    assert report["weight_payload_bytes_read"] == 0
    assert list(tmp_path.iterdir()) == [root]
