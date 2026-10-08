"""Finite inputs, static diagnostics and strict JSON for untrusted metadata."""

import json
import math
from dataclasses import dataclass

MIB = 1024 * 1024


class InspectionError(Exception):
    def __init__(self, code: str, category: str = "invalid"):
        self.code = code
        self.category = category
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    config_bytes: int = MIB
    index_bytes: int = 32 * MIB
    header_bytes: int = 32 * MIB
    auxiliary_bytes: int = 64 * MIB
    total_read_bytes: int = 256 * MIB
    directory_entries: int = 512
    shards: int = 64
    tensors: int = 500_000
    json_nodes: int = 4_000_000
    json_depth: int = 64

    def __post_init__(self):
        maxima = (
            MIB,
            32 * MIB,
            32 * MIB,
            64 * MIB,
            256 * MIB,
            512,
            64,
            500_000,
            4_000_000,
            64,
        )
        for name, maximum in zip(self.__dataclass_fields__, maxima, strict=True):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(
                    "Inspection limits must be positive within hard bounds"
                )


@dataclass
class Budget:
    maximum: int
    read_bytes: int = 0

    def consume(self, count: int):
        if count < 0 or self.read_bytes + count > self.maximum:
            raise InspectionError("TOTAL_READ_LIMIT", "unsupported")
        self.read_bytes += count


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InspectionError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _integer(value):
    if len(value) > 21:
        raise InspectionError("JSON_NUMBER_LIMIT", "unsupported")
    return int(value)


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise InspectionError("JSON_NONFINITE")
    return result


def _constant(_):
    raise InspectionError("JSON_NONFINITE")


def strict_json(data: bytes, limits: Limits):
    # Bound nesting before invoking the recursive stdlib decoder.
    depth = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            depth += 1
            if depth > limits.json_depth:
                raise InspectionError("JSON_DEPTH_LIMIT", "unsupported")
        elif byte in (125, 93):
            depth -= 1
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_int=_integer,
            parse_float=_float,
            parse_constant=_constant,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise InspectionError("JSON_MALFORMED") from None
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > limits.json_nodes:
            raise InspectionError("JSON_NODE_LIMIT", "unsupported")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


def text(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise InspectionError("METADATA_TEXT_INVALID")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise InspectionError("METADATA_TEXT_INVALID")
    return value
