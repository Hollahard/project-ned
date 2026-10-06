"""Native read-only tools for Friday (Risk 0)."""

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict

from friday.tools.base import Tool, ToolResult


class FilesystemReadTool(Tool):
    name = "filesystem.read"
    description = "Read the content of a file within the workspace."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative or absolute path to the file"},
            "max_lines": {"type": "integer", "description": "Maximum lines to read", "default": 200},
        },
        "required": ["path"],
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"])
        max_lines = arguments.get("max_lines", 200)

        if not path.is_file():
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"File not found: {path}",
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
            content = "".join(lines)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=content,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )


class FilesystemListTool(Tool):
    name = "filesystem.list"
    description = "List entries in a directory within the workspace."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list", "default": "."},
        },
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        dir_path = Path(arguments.get("path", "."))
        if not dir_path.is_dir():
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Not a directory: {dir_path}",
            )

        try:
            entries = []
            for item in sorted(dir_path.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                entries.append(f"{prefix} {item.name}")
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output="\n".join(entries),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )


class GitStatusTool(Tool):
    name = "git.status"
    description = "Check git status in the repository."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            res = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                check=False,
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=res.returncode == 0,
                output=res.stdout or "(clean)",
                error=res.stderr if res.returncode != 0 else None,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )


class GitDiffTool(Tool):
    name = "git.diff"
    description = "View unstaged changes in git."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "default": False},
        },
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        cmd = ["git", "diff"]
        if arguments.get("staged"):
            cmd.append("--staged")
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=res.returncode == 0,
                output=res.stdout or "(no diff)",
                error=res.stderr if res.returncode != 0 else None,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )


class SystemInfoTool(Tool):
    name = "system.info"
    description = "Retrieve basic operating system and platform information."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
        }
        output_str = "\n".join(f"{k}: {v}" for k, v in info.items())
        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=True,
            output=output_str,
            metadata=info,
        )
