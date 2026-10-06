"""Parser and validator for SKILL.md.

Invariants:
1. One file, no graph. Body is text. No includes, no URLs, no hooks.
2. Frontmatter extra keys strictly forbidden via Pydantic extra='forbid'.
3. Slug and NTFS: strict slug regex, DOS device names rejected, Alternate Data Streams rejected.
4. Tool identity: NFKC, ASCII-only regex, homoglyphs/lookalikes fail closed.
5. Paths containment: each path must resolve inside workspace_root.
6. High-entropy blobs and privilege bypass phrases fail closed.
"""

import math
import re
import unicodedata
from pathlib import Path
from typing import List, Optional
import yaml
from pydantic import BaseModel, ConfigDict, Field

from friday.security.paths import is_contained_in, get_canonical_path

# Windows DOS device names (case-insensitive)
RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Forbidden privilege phrases
BYPASS_PHRASES = [
    "always approve",
    "ignore policy",
    "bypass approval",
    "bypass confirmation",
    "elevate privileges",
    "as system",
    "pre-cleared",
    "grant tool",
    "treat subsequent saves as pre-cleared",
]

CREDENTIAL_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
    re.compile(r"(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|AIza[0-9A-Za-z-_]{35})"),
    re.compile(r"(?:Bearer\s+[a-zA-Z0-9_\-\.]{25,})"),
]


def calculate_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not text:
        return 0.0
    entropy = 0.0
    length = len(text)
    freq = {}
    for c in text:
        freq[c] = freq.get(c, 0) + 1
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def validate_slug(name: str) -> None:
    """Validate skill name as a safe NTFS slug.
    
    Rejects:
    - Trailing dots or trailing spaces
    - Colons (NTFS Alternate Data Streams)
    - Windows DOS device names (CON, AUX, NUL, COM1-9, etc.) with or without extensions
    - Characters not matching ^[a-z0-9][a-z0-9_-]{1,63}$
    """
    if not name or not isinstance(name, str):
        raise ValueError("Skill name must be a non-empty string.")

    if name.endswith(".") or name.endswith(" "):
        raise ValueError(f"Skill name '{name}' cannot end with a dot or space (NTFS violation).")

    if ":" in name:
        raise ValueError(f"Skill name '{name}' contains a colon (Alternate Data Stream violation).")

    # Check Windows reserved device names, including stripped extension (e.g. CON.txt or AUX.)
    base_name = name.split(".")[0].upper()
    if base_name in RESERVED_DEVICE_NAMES or name.upper() in RESERVED_DEVICE_NAMES:
        raise ValueError(f"Skill name '{name}' is a reserved Windows DOS device name.")

    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", name):
        raise ValueError(
            f"Skill name '{name}' does not match slug pattern ^[a-z0-9][a-z0-9_-]{{1,63}}$."
        )


def validate_tool_identifier(tool_id: str) -> str:
    """Validate tool identifier using NFKC normalization and strict ASCII syntax.
    
    Rejects homoglyphs, Cyrillic lookalikes, whitespace, or invalid symbols.
    """
    if not tool_id or not isinstance(tool_id, str):
        raise ValueError("Tool ID must be a non-empty string.")

    normalized = unicodedata.normalize("NFKC", tool_id)
    if not normalized.isascii():
        raise ValueError(f"Tool ID '{tool_id}' contains non-ASCII characters or homoglyphs.")

    if not re.match(r"^[a-zA-Z0-9_.-]+$", normalized):
        raise ValueError(f"Tool ID '{tool_id}' contains invalid characters.")

    return normalized


class SkillFrontmatter(BaseModel):
    """Pydantic model for SKILL.md YAML frontmatter with strict closed schema."""
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    tools: List[str] = Field(default_factory=list)
    paths: List[str] = Field(default_factory=list)


class SkillDefinition:
    """Parsed representation of a verified SKILL.md."""

    def __init__(
        self,
        frontmatter: SkillFrontmatter,
        body: str,
        raw_text: str,
        is_sensitive: bool = False,
    ) -> None:
        self.frontmatter = frontmatter
        self.name = frontmatter.name
        self.description = frontmatter.description
        self.tools = frontmatter.tools
        self.paths = frontmatter.paths
        self.body = body
        self.raw_text = raw_text
        self.is_sensitive = is_sensitive


class SkillParser:
    """Parser for SKILL.md files enforcing all Phase 10 security invariants."""

    MAX_BODY_BYTES = 64 * 1024  # 64 KB

    @classmethod
    def parse(
        cls,
        content: str | bytes,
        workspace_root: Path | str,
        allow_sensitive: bool = False,
    ) -> SkillDefinition:
        """Parse raw SKILL.md text into a validated SkillDefinition."""
        if isinstance(content, bytes):
            text = content.decode("utf-8-sig")
        else:
            text = content

        workspace_canon = get_canonical_path(workspace_root)

        # Check raw text for obvious privilege bypass phrases
        lower_text = text.lower()
        for phrase in BYPASS_PHRASES:
            if phrase in lower_text:
                raise ValueError(f"Skill content contains forbidden privilege phrase: '{phrase}'.")

        # Check for include syntax, graph links, script tags
        if re.search(r"\{\{\s*include\b|!\[\[|<script\b|<iframe\b", text, re.IGNORECASE):
            raise ValueError("Skill content contains forbidden transclusion, script, or graph syntax.")

        # Extract YAML frontmatter
        fm_match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.DOTALL)
        if not fm_match:
            raise ValueError("SKILL.md must start with YAML frontmatter bounded by '---'.")

        yaml_text = fm_match.group(1)
        body_text = fm_match.group(2)

        if len(body_text.encode("utf-8")) > cls.MAX_BODY_BYTES:
            raise ValueError(f"Skill body exceeds maximum size of {cls.MAX_BODY_BYTES} bytes.")

        # Parse YAML
        try:
            raw_dict = yaml.safe_load(yaml_text)
        except Exception as e:
            raise ValueError(f"Malformed YAML frontmatter: {e}")

        if not isinstance(raw_dict, dict):
            raise ValueError("YAML frontmatter must be a key-value dictionary.")

        # Validate with Pydantic (extra="forbid" rejects any unapproved keys)
        try:
            frontmatter = SkillFrontmatter(**raw_dict)
        except Exception as e:
            raise ValueError(f"Frontmatter schema validation failed: {e}")

        # Validate name slug
        validate_slug(frontmatter.name)

        # Validate tool identifiers
        clean_tools = []
        for tid in frontmatter.tools:
            clean_tools.append(validate_tool_identifier(tid))
        frontmatter.tools = clean_tools

        # Validate paths containment
        for path_str in frontmatter.paths:
            p = (workspace_canon / path_str).resolve()
            if not is_contained_in(p, workspace_canon):
                raise ValueError(
                    f"Skill declared path '{path_str}' escapes workspace root '{workspace_canon}'."
                )

        # High-entropy and credential detection in body
        is_sensitive = False
        for pat in CREDENTIAL_PATTERNS:
            if pat.search(body_text):
                is_sensitive = True
                break

        if not is_sensitive:
            # Check entropy of long tokens
            words = re.findall(r"\S{20,}", body_text)
            for w in words:
                if calculate_entropy(w) > 4.5:
                    is_sensitive = True
                    break

        if is_sensitive and not allow_sensitive:
            raise ValueError(
                "High-entropy or credential-shaped content detected in skill body. "
                "Must be explicitly acknowledged as sensitive via native approval."
            )

        return SkillDefinition(
            frontmatter=frontmatter,
            body=body_text,
            raw_text=text,
            is_sensitive=is_sensitive,
        )
