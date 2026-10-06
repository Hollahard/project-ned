"""Security policy engine governing tool invocation."""

import logging
from pathlib import Path
from typing import Any, Dict
from friday.security.paths import is_path_within_root
from friday.security.tokens import CapabilityTokenManager
from friday.tools.base import Tool

logger = logging.getLogger(__name__)


class PolicyDecision:
    def __init__(
        self,
        allowed: bool,
        requires_approval: bool = False,
        reason: str = "",
        canonical_args: Dict[str, Any] | None = None,
    ) -> None:
        self.allowed = allowed
        self.requires_approval = requires_approval
        self.reason = reason
        self.canonical_args = canonical_args or {}


class PolicyEngine:
    """Evaluates whether a tool call may proceed, must be approved, or is rejected."""

    def __init__(
        self,
        token_manager: CapabilityTokenManager,
        safe_roots: list[Path] | None = None,
        approval_level: int = 1,
    ) -> None:
        self.token_manager = token_manager
        self.safe_roots = safe_roots or [Path.cwd()]
        self.approval_level = approval_level

    def evaluate(
        self,
        tool: Tool,
        arguments: Dict[str, Any],
        capability_token: str | None = None,
    ) -> PolicyDecision:
        """Evaluate a tool invocation against security invariants."""
        clean_args = dict(arguments)
        if not capability_token:
            capability_token = clean_args.pop("capability_token", None) or clean_args.pop("_capability_token", None)

        # Check path boundaries if the tool targets a filesystem path
        if "path" in clean_args or "target_path" in clean_args:
            target_path = Path(clean_args.get("path") or clean_args.get("target_path"))
            within_any_root = any(is_path_within_root(target_path, root) for root in self.safe_roots)
            if not within_any_root:
                # Target path is outside approved safe roots
                if tool.risk_level >= 1:
                    logger.warning("Rejected write outside safe root: %s", target_path)
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Path {target_path} is outside configured safe roots",
                    )
                else:
                    # Reading outside safe root requires explicit native approval
                    if not capability_token:
                        return PolicyDecision(
                            allowed=False,
                            requires_approval=True,
                            reason="Reading outside safe workspace root requires user approval",
                            canonical_args=clean_args,
                        )

        # Determine effective risk level (supports dynamic classifier on tools like memory.save)
        effective_risk = tool.classify_risk(clean_args) if hasattr(tool, "classify_risk") else tool.risk_level

        # High risk tools (exec, script, destructive, or elevated dynamic risk) ALWAYS require native approval
        if effective_risk >= 2 or tool.requires_approval:
            if not capability_token:
                return PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    reason=f"Tool {tool.name} (risk={effective_risk}) requires native OS approval",
                    canonical_args=clean_args,
                )

        # If a capability token was supplied, verify and consume it
        if capability_token:
            valid = self.token_manager.consume_token(capability_token, tool.name, clean_args)
            if not valid:
                return PolicyDecision(
                    allowed=False,
                    reason="Invalid, expired, or mismatched one-shot capability token",
                )
            return PolicyDecision(allowed=True, reason="Authorized via valid one-shot capability token")


        # Risk 0 read tools inside safe root are allowed automatically
        if tool.risk_level == 0:
            return PolicyDecision(allowed=True, reason="Safe read within root")

        # Safe writes within root (Risk 1)
        if tool.risk_level == 1:
            if self.approval_level == 0:
                # Strict mode: prompt for all writes
                return PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    reason="Write approval required by policy configuration",
                    canonical_args=arguments,
                )
            return PolicyDecision(allowed=True, reason="Safe write within root")

        return PolicyDecision(allowed=False, reason="Denied by default policy")
