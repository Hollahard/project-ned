"""Native filesystem write and rollback tools with pre-write Git checkpoints (Risk 1)."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.security.paths import is_path_within_root
from friday.storage.checkpoints import CheckpointManager, default_checkpoint_manager
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class FilesystemWriteTool(Tool):
    """Safely writes file content within safe workspace roots with pre-write Git checkpoints."""

    name = "filesystem.write"
    description = "Write text content to a file within the workspace with pre-write Git checkpoints."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative or absolute path to the target file"},
            "content": {"type": "string", "description": "Text content to write to the file"},
            "create_directories": {
                "type": "boolean",
                "description": "Create parent directories if they do not exist",
                "default": True,
            },
            "checkpoint": {
                "type": "boolean",
                "description": "Capture pre-write checkpoint for rollback",
                "default": True,
            },
        },
        "required": ["path", "content"],
    }

    def __init__(
        self,
        checkpoint_manager: Optional[CheckpointManager] = None,
        safe_roots: Optional[List[Path]] = None,
    ) -> None:
        self.checkpoint_manager = checkpoint_manager or default_checkpoint_manager
        self.safe_roots = safe_roots or [Path.cwd()]

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        raw_path = str(arguments["path"])
        content = str(arguments["content"])
        create_dirs = bool(arguments.get("create_directories", True))
        capture_checkpoint = bool(arguments.get("checkpoint", True))

        # 1. Reject Alternate Data Streams (ADS)
        drive, part = os.path.splitdrive(raw_path)
        if ":" in part:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Rejected path containing stream delimiter: {raw_path}",
            )

        target_path = Path(raw_path).resolve()

        # 2. Defense-in-depth: Verify path containment within safe roots
        if self.safe_roots and not any(is_path_within_root(target_path, root) for root in self.safe_roots):
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Target path is outside configured safe roots: {target_path}",
            )

        checkpoint_id = None
        git_blob_hash = None

        # 3. Capture pre-write checkpoint
        if capture_checkpoint:
            try:
                cp = self.checkpoint_manager.create_checkpoint(target_path)
                checkpoint_id = cp.checkpoint_id
                git_blob_hash = cp.git_blob_hash
            except Exception as exc:
                logger.warning("Failed to create checkpoint for %s: %s", target_path, exc)

        # 4. Create parent directories if requested
        try:
            if create_dirs and not target_path.parent.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)

            # 5. Atomic write via temporary file in same directory
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as tf:
                tf.write(content)
                tf.flush()
                os.fsync(tf.fileno())
                temp_file = Path(tf.name)

            os.replace(temp_file, target_path)

            bytes_written = len(content.encode("utf-8"))
            metadata: Dict[str, Any] = {
                "bytes_written": bytes_written,
                "path": str(target_path),
            }
            if checkpoint_id:
                metadata["checkpoint_id"] = checkpoint_id
            if git_blob_hash:
                metadata["git_blob_hash"] = git_blob_hash

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Successfully wrote {bytes_written} bytes to {target_path}",
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Failed writing to file %s: %s", target_path, exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Filesystem write failed: {exc}",
            )


class FilesystemRollbackTool(Tool):
    """Restores a file to its pre-write checkpoint state (Risk 1)."""

    name = "filesystem.rollback"
    description = "Rollback a file to a previous checkpoint captured before modification."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "checkpoint_id": {"type": "string", "description": "The ID of the checkpoint to restore"},
        },
        "required": ["checkpoint_id"],
    }

    def __init__(self, checkpoint_manager: Optional[CheckpointManager] = None) -> None:
        self.checkpoint_manager = checkpoint_manager or default_checkpoint_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        checkpoint_id = arguments["checkpoint_id"]
        success = self.checkpoint_manager.rollback(checkpoint_id)
        if success:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Successfully rolled back to checkpoint {checkpoint_id}",
                metadata={"checkpoint_id": checkpoint_id},
            )
        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=False,
            output="",
            error=f"Rollback failed: checkpoint {checkpoint_id} not found or restoration failed",
        )
