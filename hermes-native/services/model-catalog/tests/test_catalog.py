import json
import os
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from hermes_model_catalog import Limits, inspect_model
from hermes_model_catalog.common import InspectionError, strict_json
from hermes_model_catalog.paths import GrantedDirectory, _local_root


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def shard(path, header=None, payload=b"\0\0\0\0"):
    if header is None:
        header = {
            "layer.trellis": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}
        }
    raw = header if isinstance(header, bytes) else json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)


@pytest.fixture
def model(tmp_path):
    folder = tmp_path / "model"
    folder.mkdir()
    write_json(
        folder / "config.json",
        {
            "architectures": ["LlamaForCausalLM"],
            "model_type": "llama",
            "quantization_config": {"quant_method": "exl3", "bits": 5.0},
        },
    )
    shard(folder / "model.safetensors")
    return folder


def inspect(folder, limits=None):
    return inspect_model(folder.parent, folder.name, limits).as_dict()


def codes(report):
    return {issue["code"] for issue in report["issues"]}


def test_success_is_metadata_only_and_stable_fingerprint_does_not_hash_weights(model):
    result = inspect(model)
    assert result["status"] == "metadata_inspected"
    assert result["format"] == "EXL3"
    assert result["observed_tensor_count"] == 1
    assert result["runtime_compatible"] is None
    assert result["load_certified"] is False
    assert result["weights_content_hashed"] is False
    assert result["weight_payload_bytes_read"] == 0
    original = result["metadata_fingerprint"]
    assert inspect(model)["metadata_fingerprint"] == original
    weights = model / "model.safetensors"
    data = weights.read_bytes()
    weights.write_bytes(data[:-4] + b"1234")
    assert inspect(model)["metadata_fingerprint"] == original
    write_json(model / "tokenizer_config.json", {"chat_template": "synthetic template"})
    assert inspect(model)["metadata_fingerprint"] != original


@pytest.mark.parametrize(
    "name",
    [
        "../model",
        "model/child",
        "model\\child",
        "C:\\model",
        "model:stream",
        "..",
        "NUL",
        "model.",
        "model ",
    ],
)
def test_host_grant_rejects_traversal_devices_and_ads(model, name):
    result = inspect_model(model.parent, name).as_dict()
    assert result["status"] == "security"
    assert result["bytes_read"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows path and drive boundary")
def test_unc_device_relative_and_mapped_network_roots_denied(model, monkeypatch):
    for root in [Path(r"\\server\share"), Path(r"\\?\C:\root"), Path("relative")]:
        with pytest.raises(InspectionError):
            _local_root(root)

    class FakeKernel:
        class Function:
            def __call__(self, _):
                return 4

        GetDriveTypeW = Function()

    import ctypes

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_, **__: FakeKernel())
    with pytest.raises(InspectionError, match="NETWORK_OR_DEVICE_ROOT_DENIED"):
        _local_root(model.parent)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b'{"a":1,"a":2}', "JSON_DUPLICATE_KEY"),
        (b'{"a":{"b":1,"b":2}}', "JSON_DUPLICATE_KEY"),
        (b'{"a":NaN}', "JSON_NONFINITE"),
        (b'{"a":Infinity}', "JSON_NONFINITE"),
        (b'{"a":1e999}', "JSON_NONFINITE"),
        (b'{"a":"\xff"}', "JSON_MALFORMED"),
    ],
)
def test_strict_json_duplicates_nonfinite_unicode(raw, expected):
    with pytest.raises(InspectionError, match=expected):
        strict_json(raw, Limits())


def test_json_depth_node_and_file_limits_are_unsupported(model):
    with pytest.raises(InspectionError) as failure:
        strict_json(b"[[[[0]]]]", replace(Limits(), json_depth=3))
    assert failure.value.category == "unsupported"
    with pytest.raises(InspectionError, match="JSON_NODE_LIMIT"):
        strict_json(b"[1,2,3]", replace(Limits(), json_nodes=2))
    result = inspect(model, replace(Limits(), config_bytes=1))
    assert "METADATA_FILE_LIMIT" in codes(result)
    assert result["status"] == "unsupported"
    assert "SAFETENSORS_HEADER_LIMIT" in codes(
        inspect(model, replace(Limits(), header_bytes=1))
    )
    assert "TOTAL_READ_LIMIT" in codes(
        inspect(model, replace(Limits(), total_read_bytes=1))
    )


@pytest.mark.parametrize(
    "descriptor,payload,expected",
    [
        (
            {"dtype": "I16", "shape": [3], "data_offsets": [0, 4]},
            b"1234",
            "SAFETENSORS_SHAPE_SIZE_MISMATCH",
        ),
        (
            {"dtype": "I16", "shape": [2], "data_offsets": [-1, 3]},
            b"1234",
            "SAFETENSORS_OFFSETS_INVALID",
        ),
        (
            {"dtype": "I16", "shape": [2], "data_offsets": [0, 9]},
            b"1234",
            "SAFETENSORS_OFFSETS_INVALID",
        ),
        (
            {"dtype": "I16", "shape": [True], "data_offsets": [0, 2]},
            b"12",
            "SAFETENSORS_SHAPE_OR_OFFSETS_INVALID",
        ),
        (
            {"dtype": "I16", "shape": [1], "data_offsets": [True, 2]},
            b"12",
            "SAFETENSORS_SHAPE_OR_OFFSETS_INVALID",
        ),
        (
            {"dtype": "I16", "shape": [0], "data_offsets": [0, 0]},
            b"12",
            "SAFETENSORS_UNINDEXED_PAYLOAD",
        ),
    ],
)
def test_bad_tensor_shapes_and_offsets(model, descriptor, payload, expected):
    shard(model / "model.safetensors", {"w": descriptor}, payload)
    result = inspect(model)
    assert result["status"] == "invalid"
    assert expected in codes(result)


def test_unknown_dtype_and_rank_are_unsupported_not_corruption(model):
    shard(
        model / "model.safetensors",
        {"w": {"dtype": "F4_NEW", "shape": [8], "data_offsets": [0, 4]}},
    )
    result = inspect(model)
    assert result["status"] == "unsupported" and "DTYPE_UNSUPPORTED" in codes(result)
    shard(
        model / "model.safetensors",
        {"w": {"dtype": "U8", "shape": [1] * 33, "data_offsets": [0, 1]}},
        b"x",
    )
    result = inspect(model)
    assert result["status"] == "unsupported" and "TENSOR_RANK_LIMIT" in codes(result)


@pytest.mark.parametrize("second", [(1, 3), (3, 5)])
def test_overlapping_or_holey_tensors(model, second):
    start, end = second
    shard(
        model / "model.safetensors",
        {
            "a": {"dtype": "U8", "shape": [2], "data_offsets": [0, 2]},
            "b": {"dtype": "U8", "shape": [2], "data_offsets": [start, end]},
        },
        b"12345",
    )
    assert "SAFETENSORS_OVERLAP_OR_HOLE" in codes(inspect(model))


def test_scalar_and_zero_length_tensor_shapes(model):
    shard(
        model / "model.safetensors",
        {
            "empty": {"dtype": "I16", "shape": [4, 0], "data_offsets": [0, 0]},
            "scalar": {"dtype": "I16", "shape": [], "data_offsets": [0, 2]},
        },
        b"12",
    )
    assert inspect(model)["status"] == "metadata_inspected"


def test_duplicate_header_key_and_malformed_header_length(model):
    shard(model / "model.safetensors", b'{"a":{},"a":{}}')
    assert "JSON_DUPLICATE_KEY" in codes(inspect(model))
    (model / "model.safetensors").write_bytes(struct.pack("<Q", 400) + b"{}")
    assert "SAFETENSORS_HEADER_INVALID" in codes(inspect(model))


def indexed(model, missing=False):
    (model / "model.safetensors").unlink()
    first = "model-00001-of-00002.safetensors"
    second = "model-00002-of-00002.safetensors"
    shard(model / first, {"a": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}})
    if not missing:
        shard(
            model / second,
            {"b": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}},
        )
    write_json(
        model / "model.safetensors.index.json",
        {"metadata": {"total_size": 8}, "weight_map": {"a": first, "b": second}},
    )
    return first, second


def test_missing_shard_retains_inspected_existing_metadata(model):
    first, second = indexed(model, True)
    result = inspect(model)
    assert result["status"] == "incomplete"
    assert result["missing_shards"] == [second]
    assert result["shards"][0]["file"] == first
    assert result["observed_tensor_count"] == 1
    assert result["index_tensor_count"] == 2


def test_index_crosscheck_duplicate_unreferenced_and_wrong_tensor(model):
    first, second = indexed(model)
    assert inspect(model)["status"] == "metadata_inspected"
    shard(model / second, {"a": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}})
    result = inspect(model)
    assert {"DUPLICATE_TENSOR_ACROSS_SHARDS", "INDEX_TENSOR_MAP_MISMATCH"} <= codes(
        result
    )
    shard(model / "extra.safetensors")
    assert "UNREFERENCED_WEIGHT_SHARD" in codes(inspect(model))


@pytest.mark.parametrize(
    "reference",
    [
        "../escape.safetensors",
        "dir/escape.safetensors",
        r"C:\escape.safetensors",
        "model.safetensors:ads",
    ],
)
def test_index_cannot_escape_grant(model, reference):
    write_json(model / "model.safetensors.index.json", {"weight_map": {"w": reference}})
    assert inspect(model)["status"] == "security"


def test_index_numbering_and_total_size_mismatch(model):
    first, second = indexed(model)
    write_json(model / "model.safetensors.index.json", {"weight_map": {"a": first}})
    assert "INDEX_SHARD_NUMBERING_INCONSISTENT" in codes(inspect(model))
    write_json(
        model / "model.safetensors.index.json",
        {"weight_map": {"a": first, "b": second}, "metadata": {"total_size": 9}},
    )
    assert "INDEX_TOTAL_SIZE_MISMATCH" in codes(inspect(model))


@pytest.mark.parametrize(
    "method,label", [("exl2", "EXL2"), ("gptq", "GPTQ"), ("newformat", "unknown")]
)
def test_declared_formats_without_loading_engines(model, method, label):
    config = json.loads((model / "config.json").read_text())
    config["quantization_config"]["quant_method"] = method
    write_json(model / "config.json", config)
    shard(
        model / "model.safetensors",
        {"w": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}},
    )
    result = inspect(model)
    assert result["format"] == label and result["runtime_compatible"] is None


def test_declared_format_conflicting_with_header_markers(model):
    shard(
        model / "model.safetensors",
        {"w.q_weight": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}},
    )
    assert "CONFLICTING_QUANTIZATION_MARKERS" in codes(inspect(model))


def test_gguf_magic_is_observed_but_not_parsed_or_certified(model):
    (model / "model.safetensors").unlink()
    (model / "model.gguf").write_bytes(b"GGUFrest")
    result = inspect(model)
    assert result["format"] == "GGUF_unsupported" and result["status"] == "unsupported"
    assert result["bytes_read"] == 8
    (model / "model.gguf").write_bytes(b"NOPErest")
    assert "GGUF_MAGIC_INVALID" in codes(inspect(model))


def test_auxiliary_fingerprint_is_opaque_bounded_and_does_not_execute_code(model):
    (model / "tokenizer_config.json").write_text(
        '{"chat_template":"SECRET_SENTINEL","x":1,"x":2}'
    )
    (model / "evil.py").write_text('raise RuntimeError("must not execute")')
    result = inspect(model)
    assert result["status"] == "metadata_inspected"
    assert "SECRET_SENTINEL" not in json.dumps(result)
    assert result["metadata"][-1]["scope"] == "opaque_auxiliary_file"
    assert "AUXILIARY_FILE_LIMIT" in codes(
        inspect(model, replace(Limits(), auxiliary_bytes=1))
    )


def test_metadata_change_invalidate_fingerprint(model):
    first = inspect(model)["metadata_fingerprint"]
    config = json.loads((model / "config.json").read_text())
    config["quantization_config"]["bits"] = 4
    write_json(model / "config.json", config)
    assert inspect(model)["metadata_fingerprint"] != first


def test_second_read_mismatch_reports_changed(model, monkeypatch):
    original = GrantedDirectory.read
    calls = 0

    def changed(self, stream, count):
        nonlocal calls
        data = original(self, stream, count)
        calls += 1
        return b"x" + data[1:] if calls == 2 else data

    monkeypatch.setattr(GrantedDirectory, "read", changed)
    assert "FILE_CHANGED" in codes(inspect(model))


def test_directory_change_during_inspection_detected(model, monkeypatch):
    original = GrantedDirectory.revalidate

    def changed(self):
        (self.path / "new-model-file").write_bytes(b"new")
        return original(self)

    monkeypatch.setattr(GrantedDirectory, "revalidate", changed)
    assert "DIRECTORY_CHANGED" in codes(inspect(model))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_reparse_directory_cannot_escape_grant(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    # The fixture creates only its own disposable junction, never a model link.
    result = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    try:
        report = inspect_model(root, "linked").as_dict()
        assert report["status"] == "security" and report["bytes_read"] == 0
    finally:
        os.rmdir(link)


def test_unicode_space_and_long_paths_work_without_copy(model):
    nested = model.parent / ("long-" + "a" * 90) / ("long-" + "b" * 90)
    nested.mkdir(parents=True)
    renamed = nested / "モデル with spaces"
    model.rename(renamed)
    result = inspect(renamed)
    assert result["status"] == "metadata_inspected"


def test_cli_isolated_without_site_packages_or_gpu_imports(model):
    cli = Path(__file__).parents[1] / "inspect_model.py"
    result = subprocess.run(
        [
            sys._base_executable,
            "-I",
            "-S",
            "-B",
            str(cli),
            "--root",
            str(model.parent),
            "--model",
            model.name,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert (
        report["load_certified"] is False and report["status"] == "metadata_inspected"
    )


def test_no_weight_payload_read_even_when_payload_contains_canary(model, monkeypatch):
    weights = model / "model.safetensors"
    secret_payload = b"WEIGHT_PAYLOAD_MUST_NEVER_BE_READ"
    shard(
        weights,
        {
            "w.trellis": {
                "dtype": "U8",
                "shape": [len(secret_payload)],
                "data_offsets": [0, len(secret_payload)],
            }
        },
        secret_payload,
    )
    prefix = weights.read_bytes()[:8]
    boundary = 8 + struct.unpack("<Q", prefix)[0]
    identity = weights.stat().st_ino
    original = GrantedDirectory.read
    reads = []

    def guarded(self, stream, count):
        if os.fstat(stream.fileno()).st_ino == identity:
            reads.append((stream.tell(), count))
            assert stream.tell() + count <= boundary
        return original(self, stream, count)

    monkeypatch.setattr(GrantedDirectory, "read", guarded)
    result = inspect(model)
    assert result["status"] == "metadata_inspected"
    assert reads == [(0, 8), (8, boundary - 8), (0, boundary)]
    assert secret_payload.decode() not in json.dumps(result)


def test_global_tensor_limit_stops_later_shards_before_union_growth(model, monkeypatch):
    (model / "model.safetensors").unlink()
    for i in range(3):
        shard(
            model / f"part{i}.safetensors",
            {f"w{i}": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}},
        )
    import hermes_model_catalog.catalog as catalog

    original = catalog.inspect_shard
    visited = []

    def tracked(directory, name, limits):
        visited.append(name)
        return original(directory, name, limits)

    monkeypatch.setattr(catalog, "inspect_shard", tracked)
    report = inspect(model, replace(Limits(), tensors=1))
    assert "TENSOR_COUNT_LIMIT" in codes(report)
    assert report["observed_tensor_count"] == 1
    assert visited == ["part0.safetensors", "part1.safetensors"]


def test_truncated_issue_output_never_downgrades_aggregate_status():
    from hermes_model_catalog.catalog import InspectionReport, _bound_report

    report = InspectionReport("synthetic")
    for i in range(128):
        report.issue(f"UNSUPPORTED_{i}", "unsupported")
    report.issue("FILE_CHANGED", "changed")
    assert report.status == "changed"
    report.issue("PATH_DENIED", "security")
    assert report.status == "security"
    assert len(report.issues) == 128
    report.metadata = [{"synthetic_oversized_summary": "x" * 131072}]
    _bound_report(report)
    assert report.status == "security"
    assert len(json.dumps(report.as_dict()).encode()) <= 128 * 1024


@pytest.mark.parametrize(
    "field,value",
    [
        ("bits", -1),
        ("bits", 0),
        ("head_bits", True),
        ("group_size", 2.5),
        ("group_size", 0),
    ],
)
def test_invalid_quantization_numbers_are_not_accepted(model, field, value):
    config = json.loads((model / "config.json").read_text())
    config["quantization_config"][field] = value
    write_json(model / "config.json", config)
    assert "QUANTIZATION_METADATA_INVALID" in codes(inspect(model))


def test_null_in_granted_root_returns_static_security_report(model):
    report = inspect_model(Path(str(model.parent) + "\0hidden"), "model").as_dict()
    assert report["status"] == "security"
    assert report["bytes_read"] == 0
    assert "hidden" not in json.dumps(report)
