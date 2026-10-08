"""Immutable load intent; weight quantization is artifact metadata, not a knob."""

import ntpath
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields

from .errors import ProfileValidationError


def normalize_cache_mode(value: str) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("cache_mode must be a string")
    normalized = value.strip().upper()
    aliases = {"FP16": "FP16", "Q4": "4,4", "Q6": "6,6", "Q8": "8,8"}
    if normalized in aliases:
        return aliases[normalized]
    match = re.fullmatch(r"([2-8])\s*,\s*([2-8])", normalized)
    if match:
        return f"{match[1]},{match[2]}"
    raise ProfileValidationError("cache_mode requires FP16, Q4/Q6/Q8, or K,V bits in 2..8")


def normalize_observed_cache_mode(value: str) -> str:
    """Interpret the pinned backend's raw setting without masking its FP16 fallback.

    create_cache accepts uppercase aliases or anchored K,V pairs; e.g. raw `q6`
    silently selects FP16 upstream. User-friendly input normalization is unsafe here.
    Unknown raw modes fail closed rather than claiming an effective quantization.
    """
    if not isinstance(value, str):
        raise ProfileValidationError("observed cache_mode must be a string")
    aliases = {"FP16": "FP16", "Q4": "4,4", "Q6": "6,6", "Q8": "8,8"}
    if value in aliases:
        return aliases[value]
    match = re.fullmatch(r"([2-8])\s*,\s*([2-8])", value)
    if match:
        return f"{match[1]},{match[2]}"
    raise ProfileValidationError("engine reported an ambiguous cache mode with FP16 fallback")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ProfileValidationError(
            f"{field} must be a nonempty string without control characters"
        )
    return value


def canonical_model_path(value: str) -> str:
    """Compare absolute engine paths lexically; this is NOT a filesystem attestation."""
    _text(value, "expected_model_path")
    if ".." in value.replace("\\", "/").split("/"):
        raise ProfileValidationError("expected_model_path must not contain parent traversal")
    if ntpath.splitdrive(value)[0]:
        if not ntpath.isabs(value):
            raise ProfileValidationError("expected_model_path must be absolute")
        return ntpath.normcase(ntpath.normpath(value))
    if not posixpath.isabs(value):
        raise ProfileValidationError("expected_model_path must be absolute")
    return posixpath.normpath(value)


@dataclass(frozen=True, slots=True)
class LoadProfile:
    artifact_id: str
    revision: str
    model_name: str
    expected_model_path: str
    context_length: int = 4096
    cache_size: int = 4096
    cache_mode: str = "FP16"
    max_batch_size: int = 1
    chunk_size: int = 2048
    vision: bool = False

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        _text(self.revision, "revision")
        _text(self.model_name, "model_name")
        name = self.model_name.replace("\\", "/")
        if (
            name.startswith("/")
            or ":" in name
            or any(p in ("", ".", "..") for p in name.split("/"))
        ):
            raise ProfileValidationError("model_name must be relative without traversal")
        object.__setattr__(self, "model_name", name)
        object.__setattr__(
            self, "expected_model_path", canonical_model_path(self.expected_model_path)
        )
        object.__setattr__(self, "cache_mode", normalize_cache_mode(self.cache_mode))
        for field in ("context_length", "cache_size", "max_batch_size", "chunk_size"):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ProfileValidationError(f"{field} must be a positive integer")
        if self.cache_size % 256:
            raise ProfileValidationError("cache_size must be a multiple of 256")
        if self.cache_size < self.context_length:
            raise ProfileValidationError("cache_size must cover context_length")
        if self.chunk_size < 256 or self.chunk_size % 256:
            raise ProfileValidationError("chunk_size must be a positive multiple of 256")
        if type(self.vision) is not bool:
            raise ProfileValidationError("vision must be a boolean")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "LoadProfile":
        if set(values) - {f.name for f in fields(cls)}:
            raise ProfileValidationError("unsupported load profile fields")
        try:
            return cls(**values)
        except TypeError:
            raise ProfileValidationError("missing or invalid load profile fields") from None

    def payload(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "backend": "exllamav3",
            "max_seq_len": self.context_length,
            "cache_size": self.cache_size,
            "cache_mode": self.cache_mode,
            "max_batch_size": self.max_batch_size,
            "chunk_size": self.chunk_size,
            "vision": self.vision,
            "draft_model": {"draft_mode": "disabled"},
        }
