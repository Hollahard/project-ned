"""Model profiler measurement engine and immutable artifact invalidation.

Tracks:
1. Benchmark telemetry: Time-To-First-Token (TTFT), tokens/sec throughput, and VRAM utilization.
2. Immutable artifact invalidation: SHA-256 / mtime digests of weights, tokenizer, and Jinja templates.
   Immediately invalidates cached benchmark measurements if any artifact file changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkTelemetry:
    ttft_ms: float
    tokens_per_second: float
    vram_used_bytes: int
    vram_total_bytes: int
    peak_vram_bytes: int = 0

    @property
    def vram_utilization_ratio(self) -> float:
        if self.vram_total_bytes <= 0:
            return 0.0
        return self.vram_used_bytes / self.vram_total_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "ttft_ms": round(self.ttft_ms, 2),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "vram_used_bytes": self.vram_used_bytes,
            "vram_total_bytes": self.vram_total_bytes,
            "peak_vram_bytes": self.peak_vram_bytes or self.vram_used_bytes,
            "vram_utilization_ratio": round(self.vram_utilization_ratio, 4),
        }


@dataclass(frozen=True)
class ArtifactFingerprint:
    weights_digest: str
    tokenizer_digest: str
    template_digest: str
    composite_hash: str

    def matches(self, other: ArtifactFingerprint) -> bool:
        return (
            self.composite_hash == other.composite_hash
            and self.weights_digest == other.weights_digest
            and self.tokenizer_digest == other.tokenizer_digest
            and self.template_digest == other.template_digest
        )


def _hash_file_metadata(path: Path) -> str:
    """Computes deterministic digest over file size, mtime, and initial header."""
    if not path.is_file():
        return ""
    stat = path.stat()
    h = hashlib.sha256()
    h.update(str(stat.st_size).encode())
    h.update(str(stat.st_mtime_ns).encode())
    try:
        with open(path, "rb") as f:
            chunk = f.read(65536)
            h.update(chunk)
    except OSError:
        pass
    return h.hexdigest()


def compute_artifact_fingerprint(model_dir: Path | str) -> ArtifactFingerprint:
    """Calculates immutable artifact digests across weights, tokenizer, and Jinja templates."""
    root = Path(model_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    # 1. Weights digest (safetensors)
    weights_hasher = hashlib.sha256()
    weight_files = sorted(root.glob("*.safetensors"))
    for wf in weight_files:
        weights_hasher.update(wf.name.encode())
        weights_hasher.update(_hash_file_metadata(wf).encode())
    weights_digest = weights_hasher.hexdigest()

    # 2. Tokenizer digest
    tok_hasher = hashlib.sha256()
    tok_patterns = ("tokenizer.json", "tokenizer.model", "tokenizer_config.json", "vocab.json")
    for pattern in tok_patterns:
        tf = root / pattern
        if tf.is_file():
            tok_hasher.update(tf.name.encode())
            tok_hasher.update(_hash_file_metadata(tf).encode())
    tokenizer_digest = tok_hasher.hexdigest()

    # 3. Chat template digest
    template_hasher = hashlib.sha256()
    template_patterns = ("chat_template.jinja", "chat_template.json")
    for pattern in template_patterns:
        tpl = root / pattern
        if tpl.is_file():
            template_hasher.update(tpl.name.encode())
            template_hasher.update(_hash_file_metadata(tpl).encode())
    template_digest = template_hasher.hexdigest()

    # Composite fingerprint
    composite = hashlib.sha256(
        f"{weights_digest}:{tokenizer_digest}:{template_digest}".encode()
    ).hexdigest()

    return ArtifactFingerprint(
        weights_digest=weights_digest,
        tokenizer_digest=tokenizer_digest,
        template_digest=template_digest,
        composite_hash=composite,
    )


class ModelProfiler:
    """Collects benchmark telemetry and enforces immutable artifact cache invalidation."""

    def __init__(self) -> None:
        # cache key: str(model_dir.resolve()) -> (ArtifactFingerprint, BenchmarkTelemetry)
        self._cache: dict[str, tuple[ArtifactFingerprint, BenchmarkTelemetry]] = {}

    def record_benchmark(
        self,
        model_dir: Path | str,
        telemetry: BenchmarkTelemetry,
    ) -> ArtifactFingerprint:
        """Records a new benchmark measurement bound to the model's current artifact fingerprint."""
        path_str = str(Path(model_dir).resolve())
        fingerprint = compute_artifact_fingerprint(model_dir)
        self._cache[path_str] = (fingerprint, telemetry)
        logger.info("Recorded benchmark telemetry for %s: %s", path_str, telemetry.to_dict())
        return fingerprint

    def get_benchmark(self, model_dir: Path | str) -> BenchmarkTelemetry | None:
        """Retrieves cached benchmark if artifact files are completely unchanged.
        
        If any weight, tokenizer, or Jinja template file was altered, the cached measurement
        is immediately invalidated and evicted.
        """
        path_str = str(Path(model_dir).resolve())
        entry = self._cache.get(path_str)
        if entry is None:
            return None

        saved_fp, telemetry = entry
        current_fp = compute_artifact_fingerprint(model_dir)

        if not saved_fp.matches(current_fp):
            logger.warning(
                "Model artifact modified since benchmark! Invalidating cached telemetry for %s",
                path_str,
            )
            del self._cache[path_str]
            return None

        return telemetry

    def is_cache_valid(self, model_dir: Path | str) -> bool:
        """Checks whether valid, non-stale benchmark telemetry exists for model_dir."""
        return self.get_benchmark(model_dir) is not None

    def invalidate(self, model_dir: Path | str) -> None:
        """Explicitly purges cached telemetry for model_dir."""
        path_str = str(Path(model_dir).resolve())
        self._cache.pop(path_str, None)

    def clear(self) -> None:
        self._cache.clear()
