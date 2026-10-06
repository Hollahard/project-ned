"""Canonical byte normalizer, unified diff generator, and SHA-256 hasher for SKILL.md."""

import difflib
import hashlib
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def canonicalize_skill_bytes(raw_content: str | bytes) -> bytes:
    """Canonicalize skill content to deterministic UTF-8 bytes with LF endings and no BOM.
    
    Invariants:
    1. UTF-8 encoded.
    2. Strips BOM (\\ufeff).
    3. Normalizes all line endings (\\r\\n, \\r) to \\n.
    4. Ensures exactly one trailing \\n.
    """
    if isinstance(raw_content, bytes):
        # Decode UTF-8, replacing errors
        text = raw_content.decode("utf-8-sig")
    else:
        text = raw_content

    # Strip any leading BOM if still present as unicode char
    if text.startswith("\ufeff"):
        text = text[1:]

    # Normalize newlines
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # If the last element is empty because of trailing newline, strip it
    while lines and lines[-1] == "":
        lines.pop()

    # Rejoin with standard LF and exactly one trailing newline
    canonical_text = "\n".join(lines) + "\n" if lines else ""
    return canonical_text.encode("utf-8")


def compute_content_hash(canonical_bytes: bytes) -> str:
    """Compute deterministic SHA-256 hex digest of canonical bytes."""
    return hashlib.sha256(canonical_bytes).hexdigest()


def generate_skill_diff(
    old_content: str | bytes | None,
    new_content: str | bytes,
    skill_name: str,
) -> str:
    """Generate a clean unified diff for human inspection in the Win32 dialog."""
    old_canonical = canonicalize_skill_bytes(old_content).decode("utf-8") if old_content else ""
    new_canonical = canonicalize_skill_bytes(new_content).decode("utf-8")

    from_lines = old_canonical.splitlines(keepends=True)
    to_lines = new_canonical.splitlines(keepends=True)

    diff = difflib.unified_diff(
        from_lines,
        to_lines,
        fromfile=f"a/.agents/skills/{skill_name}/SKILL.md",
        tofile=f"b/.agents/skills/{skill_name}/SKILL.md",
        n=3,
    )
    return "".join(diff)
