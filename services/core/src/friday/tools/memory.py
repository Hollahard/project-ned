"""Memory tools for Project Friday with strict content classification and policy gating."""

import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.memory.coordinator import MemoryCoordinator
from friday.memory.procedural import ProceduralMemoryEntry
from friday.memory.semantic import SemanticMemoryEntry
from friday.storage.db import DatabaseManager
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

# Structural Deny Patterns: Tool namespaces and policy/privilege vocabulary
DENY_VOCABULARY_PATTERN = re.compile(
    r"(?:filesystem\.|terminal\.|git\.|mcp_[a-z0-9_]+|system\.|memory\.)|"
    r"\b(?:policy|approval|approved|allow|allowed|allowlist|whitelist|permission|privilege|modal|"
    r"capability|admin|bypass|pre-?clear|pre-?cleared|grant|override)\b",
    re.IGNORECASE,
)

SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(KEY|TOKEN|SECRET|PASSWORD|AUTH|PASSWD)\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/=]{16,}['\"]?",
    re.IGNORECASE,
)

PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)


def calculate_shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy in bits per character."""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    counts: Dict[str, int] = {}
    for char in data:
        counts[char] = counts.get(char, 0) + 1
    for count in counts.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def is_high_entropy_or_secret(text: str) -> bool:
    """Detect high-entropy tokens or secret-shaped assignments."""
    if PRIVATE_KEY_PATTERN.search(text):
        return True
    if SECRET_ASSIGNMENT_PATTERN.search(text):
        return True

    # Tokenize by whitespace and non-alphanumeric separators
    tokens = re.split(r"[\s\"'=:;,]+", text)
    for token in tokens:
        # Check contiguous alphanumeric/base64/hex strings
        if len(token) >= 20 and re.match(r"^[A-Za-z0-9_\-+/=]+$", token):
            if calculate_shannon_entropy(token) > 3.9:
                return True
    return False


def classify_memory_content(title: str, body: str) -> str:
    """
    Authoritative memory classifier.
    Returns:
      - 'DENY': Content references tools, policies, or approval vocabulary (rejected outright).
      - 'HIGH_ENTROPY': Content contains secrets or high-entropy blobs (elevated to Risk 2).
      - 'NORMAL': Regular factual knowledge or unapproved workflow steps (Risk 1).
    """
    combined = f"{title}\n{body}"

    # 1. Structural Deny Check
    if DENY_VOCABULARY_PATTERN.search(combined):
        return "DENY"

    # 2. High-Entropy / Secret Shape Check
    if is_high_entropy_or_secret(combined):
        return "HIGH_ENTROPY"

    return "NORMAL"


class MemorySearchTool(Tool):
    """Tool for searching passive memory records strictly within the active workspace."""

    name = "memory.search"
    description = (
        "Search passive historical knowledge, facts, and past records for the active workspace. "
        "Returns bounded passive data only; does not provide executable instructions or policy grants."
    )
    risk_level = 0
    requires_approval = False
    source = "native"

    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query keywords"},
            "tiers": {
                "type": "array",
                "items": {"type": "string", "enum": ["semantic", "procedural", "episodic"]},
                "description": "Optional list of memory tiers to search",
            },
            "limit": {"type": "integer", "default": 3, "description": "Max results per tier"},
        },
        "required": ["query"],
    }

    def __init__(self, coordinator: MemoryCoordinator, workspace_root: Path) -> None:
        self.coordinator = coordinator
        self.workspace_root = workspace_root.resolve()

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        tiers = arguments.get("tiers")
        limit = min(10, max(1, int(arguments.get("limit", 3))))

        if not query:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Query cannot be empty",
            )

        try:
            results = await self.coordinator.search(
                query=query,
                workspace_root=str(self.workspace_root),
                tiers=tiers,
                limit_per_tier=limit,
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=results,
            )
        except Exception as exc:
            logger.error("Memory search failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Memory search error: {exc}",
            )


class MemorySaveTool(Tool):
    """Tool for saving factual knowledge or reproduction steps into workspace memory."""

    name = "memory.save"
    description = (
        "Save factual knowledge or workflow steps into memory for the active workspace. "
        "Strictly gated by content classifiers: references to tools or policies are denied; "
        "high-entropy text requires explicit Risk 2 approval. Procedures default to unapproved."
    )
    risk_level = 1
    source = "native"

    parameters_schema = {
        "type": "object",
        "properties": {
            "tier": {"type": "string", "enum": ["semantic", "procedural"]},
            "title": {"type": "string", "description": "Title or summary of memory"},
            "content": {"type": "string", "description": "Content for semantic memory"},
            "category": {"type": "string", "default": "fact", "description": "Category for semantic memory"},
            "steps": {"type": "string", "description": "Steps for procedural memory"},
            "source": {"type": "string", "description": "Source or author reference for procedural memory"},
        },
        "required": ["tier", "title"],
    }

    def __init__(self, coordinator: MemoryCoordinator, workspace_root: Path) -> None:
        self.coordinator = coordinator
        self.workspace_root = workspace_root.resolve()

    def classify_risk(self, arguments: Dict[str, Any]) -> int:
        """Dynamic risk classifier queried by PolicyEngine."""
        title = str(arguments.get("title", ""))
        body = str(arguments.get("content") or arguments.get("steps") or "")
        classification = classify_memory_content(title, body)

        if classification == "DENY":
            return 3  # Critical: denied by default policy
        if classification == "HIGH_ENTROPY":
            return 2  # Risk 2: requires native OS approval + one-shot capability token
        return 1      # Risk 1: normal safe write within workspace

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        tier = str(arguments.get("tier", "")).lower()
        title = str(arguments.get("title", "")).strip()
        body = str(arguments.get("content") or arguments.get("steps") or "").strip()

        # 1. Authoritative classification
        classification = classify_memory_content(title, body)
        if classification == "DENY":
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Security violation: Memory content cannot reference Friday tools, policies, or approval mechanisms.",
            )

        sensitivity = "security" if classification == "HIGH_ENTROPY" else "normal"
        workspace_str = str(self.workspace_root)

        try:
            if tier == "semantic":
                content = str(arguments.get("content", "")).strip()
                category = str(arguments.get("category", "fact")).strip().lower()
                entry = SemanticMemoryEntry(
                    workspace_root=workspace_str,
                    sensitivity=sensitivity,
                    category=category,
                    title=title,
                    content=content,
                )
                entry_id = await self.coordinator.semantic.save(entry)
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=True,
                    output=f"Successfully stored semantic memory '{title}' (ID: {entry_id}, sensitivity: {sensitivity})",
                    metadata={"entry_id": entry_id, "tier": "semantic", "sensitivity": sensitivity},
                )

            elif tier == "procedural":
                steps = str(arguments.get("steps", "")).strip()
                source = str(arguments.get("source", "user_turn")).strip()
                # Enforce: approved is ALWAYS 0 for tool-saved procedures
                entry = ProceduralMemoryEntry(
                    workspace_root=workspace_str,
                    sensitivity=sensitivity,
                    title=title,
                    steps=steps,
                    source=source,
                    approved=0,  # Unapproved by default
                )
                entry_id = await self.coordinator.procedural.save(entry, is_system_authorized=False)
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=True,
                    output=f"Successfully stored procedural memory '{title}' (ID: {entry_id}, status: unapproved)",
                    metadata={"entry_id": entry_id, "tier": "procedural", "approved": False},
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Unsupported memory tier: {tier}",
                )

        except Exception as exc:
            logger.error("Failed to save memory: %s", exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Storage error: {exc}",
            )


class MemoryDeleteTool(Tool):
    """Tool for removing a memory entry from the active workspace."""

    name = "memory.delete"
    description = (
        "Delete a memory entry by ID from the active workspace. "
        "Normal entries require Risk 1; approved procedures or security-sensitive entries require Risk 2 native approval."
    )
    risk_level = 1
    source = "native"

    parameters_schema = {
        "type": "object",
        "properties": {
            "tier": {"type": "string", "enum": ["semantic", "procedural"]},
            "id": {"type": "string", "description": "UUID of memory entry to delete"},
        },
        "required": ["tier", "id"],
    }

    def __init__(self, coordinator: MemoryCoordinator, workspace_root: Path) -> None:
        self.coordinator = coordinator
        self.workspace_root = workspace_root.resolve()

    def classify_risk(self, arguments: Dict[str, Any]) -> int:
        """Dynamic risk classification for delete operations."""
        # For evaluation, if deleting a security row or approved procedure, it requires Risk 2
        # If unknown at evaluate time, defaults to Risk 1 unless marked in metadata
        tier = str(arguments.get("tier", "")).lower()
        # If arguments specifically target an approved procedure or security item, elevate to Risk 2
        if arguments.get("requires_elevated") or arguments.get("approved"):
            return 2
        return 1

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        tier = str(arguments.get("tier", "")).lower()
        entry_id = str(arguments.get("id", "")).strip()
        workspace_str = str(self.workspace_root)

        try:
            if tier == "semantic":
                entry = await self.coordinator.semantic.get(entry_id, workspace_str)
                if not entry:
                    return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=f"Semantic memory '{entry_id}' not found.")
                # Verify sensitivity gating
                if entry.sensitivity == "security" and not arguments.get("capability_token"):
                    return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error="Deleting security-sensitive memory requires native OS approval.")
                deleted = await self.coordinator.semantic.delete(entry_id, workspace_str)
            elif tier == "procedural":
                entry = await self.coordinator.procedural.get(entry_id, workspace_str)
                if not entry:
                    return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=f"Procedural memory '{entry_id}' not found.")
                if (entry.approved == 1 or entry.sensitivity == "security") and not arguments.get("capability_token"):
                    return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error="Deleting approved or sensitive procedural memory requires native OS approval.")
                deleted = await self.coordinator.procedural.delete(entry_id, workspace_str)
            else:
                return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=f"Invalid tier: {tier}")

            if deleted:
                return ToolResult(tool_name=self.name, call_id=call_id, success=True, output=f"Successfully deleted {tier} memory '{entry_id}'")
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=f"Entry '{entry_id}' could not be deleted.")

        except Exception as exc:
            logger.error("Failed to delete memory: %s", exc)
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=f"Deletion error: {exc}")
