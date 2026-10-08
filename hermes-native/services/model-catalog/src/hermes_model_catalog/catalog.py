"""Observed artifact facts, never readiness, measured quantization or GPU admission."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import InspectionError, Limits, strict_json, text
from .paths import GrantedDirectory, basename
from .tensors import inspect_shard

# Observed strings from the installed ExLlamaV3 1.5.4 source, not runtime
# qualification. No importing or evaluating that package is needed here.
REFERENCE_ARCHITECTURES = {
    "Mistral3ForConditionalGeneration",
    "Qwen3MoeForCausalLM",
    "LlamaForCausalLM",
    "Qwen3_5ForConditionalGeneration",
    "Qwen3_5ForCausalLM",
    "Qwen3_5MoeForConditionalGeneration",
    "Qwen3_5MoeForCausalLM",
}
AUXILIARY = (
    "tokenizer.json",
    "tokenizer_config.json",
    "tokenizer.model",
    "tekken.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "merges.txt",
    "chat_template.json",
    "chat_template.jinja",
    "generation_config.json",
    "quantization_config.json",
    "params.json",
    "preprocessor_config.json",
    "processor_config.json",
    "video_preprocessor_config.json",
)
SHARD_NUMBER = re.compile(r"model-(\d{5})-of-(\d{5})\.safetensors\Z")


@dataclass
class InspectionReport:
    model: str
    status: str = "metadata_inspected"
    format: str = "unknown"
    architecture: dict = field(default_factory=dict)
    quantization: dict = field(default_factory=dict)
    shards: list = field(default_factory=list)
    metadata: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    index_tensor_count: int | None = None
    observed_tensor_count: int = 0
    missing_shards: list = field(default_factory=list)
    metadata_fingerprint: str | None = None
    bytes_read: int = 0
    _categories: set[str] = field(default_factory=set, repr=False)

    def issue(self, code, category, file=None):
        self._categories.add(category)
        self.status = next(
            category
            for category in (
                "security",
                "changed",
                "invalid",
                "incomplete",
                "inaccessible",
                "unsupported",
            )
            if category in self._categories
        )
        item = {"code": code, "category": category}
        if file:
            item["file"] = file
        if item not in self.issues:
            if len(self.issues) < 128:
                self.issues.append(item)
            elif self.issues[-1]["code"] != "ISSUE_OUTPUT_LIMIT":
                self.issues[-1] = {
                    "code": "ISSUE_OUTPUT_LIMIT",
                    "category": "unsupported",
                }

    def as_dict(self):
        return {
            "schema": 1,
            "model": self.model,
            "status": self.status,
            "format": self.format,
            "architecture": self.architecture,
            "quantization": self.quantization,
            "shards": self.shards,
            "metadata": self.metadata,
            "issues": self.issues,
            "index_tensor_count": self.index_tensor_count,
            "observed_tensor_count": self.observed_tensor_count,
            "missing_shards": self.missing_shards,
            "metadata_fingerprint": self.metadata_fingerprint,
            "fingerprint_scope": "metadata_files_weight_headers_and_file_sizes",
            "fingerprint_partial": bool(self.issues),
            "bytes_read": self.bytes_read,
            "weights_content_hashed": False,
            "weight_payload_bytes_read": 0,
            "load_certified": False,
            "runtime_compatible": None,
            "registration_mode": "external_reference_inspection_only",
        }


def _config(config, report):
    if not isinstance(config, dict):
        raise InspectionError("CONFIG_OBJECT_REQUIRED")
    architectures = config.get("architectures", [])
    if not isinstance(architectures, list) or len(architectures) > 8:
        raise InspectionError("ARCHITECTURE_METADATA_INVALID")
    architectures = [text(value, 128) for value in architectures]
    model_type = config.get("model_type")
    if model_type is not None:
        model_type = text(model_type, 128)
    report.architecture = {
        "declared": architectures,
        "model_type": model_type,
        "recognized_in_reference_source": len(architectures) == 1
        and architectures[0] in REFERENCE_ARCHITECTURES,
        "reference": "installed_exllamav3_1.5.4_source_observation",
    }
    if not report.architecture["recognized_in_reference_source"]:
        report.issue("ARCHITECTURE_NOT_IN_REFERENCE_SET", "unsupported", "config.json")
    if config.get("auto_map"):
        report.issue(
            "MODEL_CODE_DECLARATION_NOT_EXECUTED", "unsupported", "config.json"
        )
    quant = config.get("quantization_config")
    if quant is None:
        report.format = "hf_unquantized_or_unspecified"
        report.quantization = {"source": "config.json", "declared_method": None}
        return
    if not isinstance(quant, dict):
        raise InspectionError("QUANTIZATION_METADATA_INVALID")
    method = quant.get("quant_method")
    if method is not None:
        method = text(method, 48).lower()
    report.format = {"exl3": "EXL3", "exl2": "EXL2", "gptq": "GPTQ"}.get(
        method, "unknown"
    )
    report.quantization = {
        "source": "config.json",
        "declared_method": method,
        "bits_are_declared_not_measured": True,
    }
    for key in ("bits", "head_bits", "group_size"):
        if key in quant:
            value = quant[key]
            if type(value) not in (int, float) or not -1 <= value <= 1_000_000:
                raise InspectionError("QUANTIZATION_METADATA_INVALID")
            if key in {"bits", "head_bits"} and value <= 0:
                raise InspectionError("QUANTIZATION_METADATA_INVALID")
            if key == "group_size" and (type(value) is not int or value == 0):
                raise InspectionError("QUANTIZATION_METADATA_INVALID")
            report.quantization[key] = value
    if report.format == "unknown":
        report.issue("QUANTIZATION_METHOD_UNSUPPORTED", "unsupported", "config.json")


def _index(data, limits):
    if not isinstance(data, dict) or not isinstance(data.get("weight_map"), dict):
        raise InspectionError("INDEX_WEIGHT_MAP_REQUIRED")
    mapping = data["weight_map"]
    if not mapping:
        raise InspectionError("INDEX_EMPTY")
    if len(mapping) > limits.tensors:
        raise InspectionError("TENSOR_COUNT_LIMIT", "unsupported")
    for tensor, shard in mapping.items():
        text(tensor, 1024)
        basename(shard)
        if not shard.endswith(".safetensors"):
            raise InspectionError("INDEX_SHARD_FORMAT_UNSUPPORTED", "unsupported")
    names = sorted(set(mapping.values()))
    if len(names) > limits.shards:
        raise InspectionError("SHARD_COUNT_LIMIT", "unsupported")
    if len({name.casefold() for name in names}) != len(names):
        raise InspectionError("INDEX_AMBIGUOUS_SHARD_NAMES")
    numbers = [SHARD_NUMBER.fullmatch(name) for name in names]
    if all(numbers):
        totals = {int(match[2]) for match in numbers}
        if (
            len(totals) != 1
            or totals != {len(names)}
            or {int(match[1]) for match in numbers} != set(range(1, len(names) + 1))
        ):
            raise InspectionError("INDEX_SHARD_NUMBERING_INCONSISTENT")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InspectionError("INDEX_METADATA_INVALID")
    total = metadata.get("total_size")
    if total is not None and (type(total) is not int or total < 0 or total > 2**63 - 1):
        raise InspectionError("INDEX_TOTAL_SIZE_INVALID")
    return mapping, names, total


def _error(report, error, file=None):
    if isinstance(error, InspectionError):
        report.issue(error.code, error.category, file)
    elif isinstance(error, FileNotFoundError):
        report.issue("FILE_MISSING", "incomplete", file)
    else:
        report.issue("FILE_ACCESS_FAILED", "inaccessible", file)


def inspect_model(
    granted_root: Path, relative_model: str, limits: Limits | None = None
):
    """Inspect a host-selected immediate child; no engine imports, writes or load.

    Errors return finite static diagnostics. Model/tokenizer/template contents
    and arbitrary exception strings are never included in the result.
    """
    limits = limits or Limits()
    report = InspectionReport(model="invalid-model-name")
    directory = None
    try:
        report.model = basename(relative_model)
        directory = GrantedDirectory(Path(granted_root), relative_model, limits)
        _inspect(directory, limits, report)
    except (InspectionError, OSError) as error:
        _error(report, error)
    if directory:
        report.bytes_read = directory.budget.read_bytes
        try:
            directory.revalidate()
        except (InspectionError, OSError) as error:
            _error(report, error)
    if report.metadata or report.shards:
        identity = {
            "schema": 1,
            "metadata": report.metadata,
            "shards": report.shards,
            "missing_shards": report.missing_shards,
        }
        report.metadata_fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    _bound_report(report)
    return report


def _bound_report(report):
    # Hard final DTO bound. A report limit is unsupported inspection, not proof
    # that the source artifact is corrupt.
    if len(json.dumps(report.as_dict()).encode()) > 128 * 1024:
        report.shards = []
        report.metadata = []
        report.issue("REPORT_SIZE_LIMIT", "unsupported")


def _inspect(directory, limits, report):
    names = directory.names
    safetensors = sorted(name for name in names if name.endswith(".safetensors"))
    gguf = sorted(name for name in names if name.lower().endswith(".gguf"))
    if gguf:
        if safetensors:
            report.issue("CONFLICTING_ARTIFACT_FORMATS", "invalid")
        if len(gguf) > limits.shards:
            raise InspectionError("SHARD_COUNT_LIMIT", "unsupported")
        valid_magic = True
        for name in gguf:
            try:
                with directory.open(name) as (stream, info):
                    prefix = directory.read(stream, 4)
                    if prefix != b"GGUF":
                        raise InspectionError("GGUF_MAGIC_INVALID")
                    stream.seek(0)
                    if directory.read(stream, 4) != prefix:
                        raise InspectionError("FILE_CHANGED", "changed")
                report.metadata.append(
                    {
                        "file": name,
                        "bytes": info.st_size,
                        "sha256": hashlib.sha256(prefix).hexdigest(),
                        "scope": "gguf_magic_and_file_size_only",
                    }
                )
            except (InspectionError, OSError) as error:
                valid_magic = False
                _error(report, error, name)
        if valid_magic:
            report.format = "GGUF_unsupported"
            report.issue("GGUF_REQUIRES_LLAMA_CPP_ADAPTER", "unsupported")
        return
    if "config.json" in names:
        try:
            data, record = directory.metadata("config.json", limits.config_bytes)
            report.metadata.append(record)
            _config(strict_json(data, limits), report)
        except (InspectionError, OSError) as error:
            _error(report, error, "config.json")
    else:
        report.issue("CONFIG_MISSING", "incomplete", "config.json")
    mapping = None
    declared_total = None
    expected = safetensors
    if "model.safetensors.index.json" in names:
        try:
            data, record = directory.metadata(
                "model.safetensors.index.json", limits.index_bytes
            )
            report.metadata.append(record)
            mapping, expected, declared_total = _index(
                strict_json(data, limits), limits
            )
            report.index_tensor_count = len(mapping)
        except (InspectionError, OSError) as error:
            _error(report, error, "model.safetensors.index.json")
    elif len(safetensors) != 1 or safetensors[0] != "model.safetensors":
        report.issue("SHARD_INDEX_REQUIRED", "incomplete")
    if not expected:
        report.issue("WEIGHT_FILES_MISSING", "incomplete")
    if len(expected) > limits.shards:
        raise InspectionError("SHARD_COUNT_LIMIT", "unsupported")
    report.missing_shards = sorted(set(expected) - names)
    for name in report.missing_shards:
        report.issue("SHARD_MISSING", "incomplete", name)
    for extra in sorted(set(safetensors) - set(expected)):
        report.issue("UNREFERENCED_WEIGHT_SHARD", "invalid", extra)
    observed = set()
    all_markers = set()
    for name in expected:
        if name not in names:
            continue
        try:
            record, tensors = inspect_shard(directory, name, limits)
            if observed.intersection(tensors):
                report.issue("DUPLICATE_TENSOR_ACROSS_SHARDS", "invalid", name)
            # Bound the prospective union BEFORE growing retained state, then
            # stop further shard reads rather than catch-and-continue globally.
            if len(observed) + len(tensors - observed) > limits.tensors:
                report.issue("TENSOR_COUNT_LIMIT", "unsupported", name)
                break
            observed.update(tensors)
            report.shards.append(record)
            all_markers.update(record["format_markers"])
            if record["unsupported_dtypes"]:
                report.issue("DTYPE_UNSUPPORTED", "unsupported", name)
            if mapping is not None and tensors != {
                key for key, shard in mapping.items() if shard == name
            }:
                report.issue("INDEX_TENSOR_MAP_MISMATCH", "invalid", name)
        except (InspectionError, OSError) as error:
            _error(report, error, name)
    report.observed_tensor_count = len(observed)
    if (
        declared_total is not None
        and not report.missing_shards
        and len(report.shards) == len(expected)
        and declared_total != sum(shard["payload_bytes"] for shard in report.shards)
    ):
        report.issue(
            "INDEX_TOTAL_SIZE_MISMATCH", "invalid", "model.safetensors.index.json"
        )
    format_markers = {
        "exl3_trellis": "EXL3",
        "exl2_q_weight": "EXL2",
        "gptq_qweight": "GPTQ",
    }
    observed_formats = {format_markers[marker] for marker in all_markers}
    if len(observed_formats) > 1 or (
        observed_formats
        and report.format in {"EXL3", "EXL2", "GPTQ"}
        and report.format not in observed_formats
    ):
        report.issue("CONFLICTING_QUANTIZATION_MARKERS", "invalid")
    elif observed_formats and report.format == "hf_unquantized_or_unspecified":
        report.format = "unknown"
        report.issue("QUANTIZED_TENSORS_WITHOUT_DECLARED_METHOD", "unsupported")
    for name in AUXILIARY:
        if name in names:
            try:
                report.metadata.append(
                    directory.fingerprint(name, limits.auxiliary_bytes)
                )
            except (InspectionError, OSError) as error:
                _error(report, error, name)
