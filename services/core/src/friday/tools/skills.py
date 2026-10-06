"""Skill management tools for Friday (Phase 10 Part A).

Tools:
- skill.list: Risk 0 (discovery metadata only)
- skill.read: Risk 0 (gated: returns metadata only if inactive, passive framed body only if user-activated)
- skill.save: Risk 2 (checkpointed atomic replace, content-hash bound token)
- skill.delete: Risk 2 (checkpointed deletion, content-hash bound token)
"""

import json
import logging
from typing import Any, Dict, Optional

from friday.security.tokens import CapabilityTokenManager
from friday.skills.diff import canonicalize_skill_bytes, compute_content_hash
from friday.skills.manager import SkillManager
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class SkillListTool(Tool):
    """List discoverable skills in the workspace (Risk 0). Metadata only."""

    name = "skill.list"
    description = "List all available skills in the workspace. Returns metadata only; body stays on disk."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, skill_manager: SkillManager) -> None:
        self.skill_manager = skill_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            skills = await self.skill_manager.list_skills()
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=json.dumps(skills, indent=2),
                metadata={"count": len(skills)},
            )
        except Exception as e:
            logger.error("skill.list failed: %s", e)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Failed to list skills: {e}",
            )


class SkillReadTool(Tool):
    """Read a skill from the workspace (Risk 0).
    
    Invariant: User-gated activation.
    If the skill has not been activated by the user in the native UI, returns INACTIVE_GATED and no body.
    """

    name = "skill.read"
    description = "Read a skill. If inactive, returns metadata only. If user-activated, returns framed body."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The slug name of the skill to read."},
        },
        "required": ["name"],
    }

    def __init__(self, skill_manager: SkillManager) -> None:
        self.skill_manager = skill_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        if not name:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Skill name is required.",
            )

        try:
            # Check if skill is active in current session
            if name not in self.skill_manager.active_skills:
                # Discover metadata to give caller inert info without exposing the body
                all_skills = await self.skill_manager.list_skills()
                meta = next((s for s in all_skills if s["name"] == name), None)
                res = {
                    "status": "INACTIVE_GATED",
                    "name": name,
                    "content_hash": meta["content_hash"] if meta else None,
                    "approved": meta["approved"] if meta else False,
                    "disabled": meta["disabled"] if meta else False,
                    "active": False,
                    "message": "Skill body is gated. It must be explicitly selected and activated by the user via the native UI picker before content can be loaded.",
                }
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=True,
                    output=json.dumps(res, indent=2),
                    metadata={"active": False, "status": "INACTIVE_GATED"},
                )

            # Active skill: inject-time read
            body = await self.skill_manager.get_skill_body_if_active(name)
            if body is None:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Skill '{name}' could not be loaded (inactive or invalidated due to content drift).",
                )

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=body,
                metadata={"active": True, "status": "ACTIVE"},
            )
        except Exception as e:
            logger.error("skill.read failed for %s: %s", name, e)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Error reading skill '{name}': {e}",
            )


class SkillSaveTool(Tool):
    """Save or update SKILL.md (Risk 2).
    
    Requires native OS confirmation and a one-shot capability token bound to the content hash.
    Ignores any client-supplied 'approved' or 'disabled' parameters.
    """

    name = "skill.save"
    description = "Create or update a skill. Requires native OS approval and capability token bound to content hash."
    risk_level = 2
    requires_approval = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The slug name of the skill."},
            "content": {"type": "string", "description": "Raw markdown text including YAML frontmatter."},
            "content_hash": {"type": "string", "description": "Expected SHA-256 hash of canonical bytes."},
            "capability_token": {"type": "string", "description": "One-shot capability token."},
            "allow_sensitive": {"type": "boolean", "description": "Acknowledge high entropy/credentials."},
        },
        "required": ["name", "content", "content_hash", "capability_token"],
    }

    def __init__(
        self,
        skill_manager: SkillManager,
        tokens_manager: CapabilityTokenManager,
    ) -> None:
        self.skill_manager = skill_manager
        self.tokens_manager = tokens_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        # Invariant: reject any client-supplied approval costume
        if "approved" in arguments:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Security violation: Client cannot specify 'approved' field.",
            )

        name = str(arguments.get("name", "")).strip()
        content = str(arguments.get("content", ""))
        content_hash = str(arguments.get("content_hash", "")).strip()
        token = str(arguments.get("capability_token", "")).strip()
        allow_sensitive = bool(arguments.get("allow_sensitive", False))

        # Check canonical bytes and compute hash
        canon_bytes = canonicalize_skill_bytes(content)
        calculated_hash = compute_content_hash(canon_bytes)
        if calculated_hash != content_hash:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Hash mismatch: calculated {calculated_hash}, argument had {content_hash}",
            )

        # Token validation: bound to tool_name and canonical args
        token_args = {
            "name": name,
            "content": content,
            "content_hash": content_hash,
        }
        if allow_sensitive:
            token_args["allow_sensitive"] = True

        if not self.tokens_manager.consume_token(token, self.name, token_args):
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Invalid, expired, or already-consumed capability token for skill.save.",
            )

        # Checkpoint and save atomically
        try:
            saved_hash = await self.skill_manager.save_skill(
                skill_name=name,
                content=canon_bytes,
                expected_content_hash=content_hash,
                allow_sensitive=allow_sensitive,
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Successfully saved skill '{name}' (content_hash: {saved_hash}). Status is inert/unapproved.",
                metadata={"name": name, "content_hash": saved_hash, "approved": False},
            )
        except Exception as e:
            logger.error("skill.save failed for %s: %s", name, e)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Failed to save skill '{name}': {e}",
            )


class SkillDeleteTool(Tool):
    """Delete a skill from disk (Risk 2).
    
    Requires native OS confirmation and a one-shot capability token.
    """

    name = "skill.delete"
    description = "Delete a skill. Requires native OS approval and capability token."
    risk_level = 2
    requires_approval = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The slug name of the skill to delete."},
            "content_hash": {"type": "string", "description": "Current SHA-256 hash of the skill."},
            "capability_token": {"type": "string", "description": "One-shot capability token."},
        },
        "required": ["name", "content_hash", "capability_token"],
    }

    def __init__(
        self,
        skill_manager: SkillManager,
        tokens_manager: CapabilityTokenManager,
    ) -> None:
        self.skill_manager = skill_manager
        self.tokens_manager = tokens_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        content_hash = str(arguments.get("content_hash", "")).strip()
        token = str(arguments.get("capability_token", "")).strip()

        token_args = {
            "name": name,
            "content_hash": content_hash,
        }

        if not self.tokens_manager.consume_token(token, self.name, token_args):
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="Invalid, expired, or already-consumed capability token for skill.delete.",
            )

        try:
            await self.skill_manager.delete_skill(name)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Successfully deleted skill '{name}'.",
                metadata={"name": name, "deleted": True},
            )
        except Exception as e:
            logger.error("skill.delete failed for %s: %s", name, e)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Failed to delete skill '{name}': {e}",
            )
