"""Safetensors structural checks using headers only; payload bytes stay unread."""

import hashlib
import struct

from .common import InspectionError, Limits, strict_json, text
from .paths import GrantedDirectory

DTYPE_BYTES = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
    "F8_E8M0": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
}


def inspect_shard(directory: GrantedDirectory, name: str, limits: Limits):
    with directory.open(name) as (stream, info):
        if info.st_size < 10:
            raise InspectionError("SAFETENSORS_TRUNCATED")
        prefix = directory.read(stream, 8)
        header_size = struct.unpack("<Q", prefix)[0]
        if header_size > limits.header_bytes:
            raise InspectionError("SAFETENSORS_HEADER_LIMIT", "unsupported")
        if header_size < 2 or header_size > info.st_size - 8:
            raise InspectionError("SAFETENSORS_HEADER_INVALID")
        raw = directory.read(stream, header_size)
        if not raw.startswith(b"{"):
            raise InspectionError("SAFETENSORS_HEADER_INVALID")
        digest = hashlib.sha256(prefix + raw).hexdigest()
        stream.seek(0)
        if (
            hashlib.sha256(directory.read(stream, 8 + header_size)).hexdigest()
            != digest
        ):
            raise InspectionError("FILE_CHANGED", "changed")
    header = strict_json(raw, limits)
    if not isinstance(header, dict):
        raise InspectionError("SAFETENSORS_HEADER_INVALID")
    metadata = header.pop("__metadata__", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(value, str) for value in metadata.values()
    ):
        raise InspectionError("SAFETENSORS_METADATA_INVALID")
    if len(header) > limits.tensors:
        raise InspectionError("TENSOR_COUNT_LIMIT", "unsupported")
    payload = info.st_size - 8 - header_size
    intervals = []
    dtypes = set()
    unsupported = set()
    markers = set()
    for key, descriptor in header.items():
        text(key, 1024)
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "dtype",
            "shape",
            "data_offsets",
        }:
            raise InspectionError("SAFETENSORS_DESCRIPTOR_INVALID")
        dtype = text(descriptor["dtype"], 32)
        shape = descriptor["shape"]
        offsets = descriptor["data_offsets"]
        if isinstance(shape, list) and len(shape) > 32:
            raise InspectionError("TENSOR_RANK_LIMIT", "unsupported")
        if (
            not isinstance(shape, list)
            or any(type(n) is not int or n < 0 or n > 2**63 - 1 for n in shape)
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or any(type(n) is not int for n in offsets)
        ):
            raise InspectionError("SAFETENSORS_SHAPE_OR_OFFSETS_INVALID")
        start, end = offsets
        if not 0 <= start <= end <= payload:
            raise InspectionError("SAFETENSORS_OFFSETS_INVALID")
        if dtype in DTYPE_BYTES:
            elements = 0 if 0 in shape else 1
            if elements:
                for extent in shape:
                    elements *= extent
                    if elements > payload + 1:
                        raise InspectionError("SAFETENSORS_SHAPE_SIZE_MISMATCH")
            if elements * DTYPE_BYTES[dtype] != end - start:
                raise InspectionError("SAFETENSORS_SHAPE_SIZE_MISMATCH")
        else:
            unsupported.add(dtype)
        dtypes.add(dtype)
        if len(dtypes) > 32:
            raise InspectionError("DTYPE_COUNT_LIMIT", "unsupported")
        intervals.append((start, end))
        if key.endswith(".trellis"):
            markers.add("exl3_trellis")
        if key.endswith(".q_weight"):
            markers.add("exl2_q_weight")
        if key.endswith(".qweight"):
            markers.add("gptq_qweight")
    position = 0
    for start, end in sorted(intervals):
        if start != position:
            raise InspectionError("SAFETENSORS_OVERLAP_OR_HOLE")
        position = end
    if position != payload:
        raise InspectionError("SAFETENSORS_UNINDEXED_PAYLOAD")
    record = {
        "file": name,
        "bytes": info.st_size,
        "header_bytes": 8 + header_size,
        "sha256": digest,
        "scope": "weight_header_and_file_size_only",
        "tensor_count": len(header),
        "payload_bytes": payload,
        "dtypes": sorted(dtypes),
        "unsupported_dtypes": sorted(unsupported),
        "format_markers": sorted(markers),
    }
    return record, set(header)
