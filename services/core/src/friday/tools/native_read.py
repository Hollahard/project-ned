"""Native read-only tools for Friday (Risk 0)."""

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict

from friday.tools.base import Tool, ToolResult


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


class FilesystemReadTool(Tool):
    name = "filesystem.read"
    description = "Read the content of a file within the workspace."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative or absolute path to the file"},
            "start_line": {"type": "integer", "description": "1-indexed starting line to read from", "default": 1},
            "max_lines": {"type": "integer", "description": "Maximum lines to read", "default": 200},
        },
        "required": ["path"],
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"])
        start_line = max(1, int(arguments.get("start_line", 1)))
        max_lines = max(1, int(arguments.get("max_lines", 200)))

        if not path.is_file():
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"File not found: {path}",
            )

        try:
            file_size = path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"File size ({file_size / (1024**2):.1f} MB) exceeds maximum allowed size (10 MB)",
                )

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = []
                for idx, line in enumerate(f, start=1):
                    if idx < start_line:
                        continue
                    lines.append(line)
                    if len(lines) >= max_lines:
                        break
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
            "recursive": {"type": "boolean", "description": "List subdirectories recursively", "default": False},
            "max_depth": {"type": "integer", "description": "Maximum depth when listing recursively", "default": 2},
            "show_hidden": {"type": "boolean", "description": "Include hidden/ignored folders like .git", "default": False},
        },
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        dir_path = Path(arguments.get("path", "."))
        recursive = bool(arguments.get("recursive", False))
        max_depth = max(1, int(arguments.get("max_depth", 2)))
        show_hidden = bool(arguments.get("show_hidden", False))

        IGNORED_NAMES = {".git", ".venv", "__pycache__", "node_modules", "target", ".pytest_cache"}

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
            if not recursive:
                for item in sorted(dir_path.iterdir()):
                    if not show_hidden and item.name in IGNORED_NAMES:
                        continue
                    prefix = "[DIR] " if item.is_dir() else "[FILE]"
                    entries.append(f"{prefix} {item.name}")
            else:
                base_depth = len(dir_path.resolve().parts)
                for root, dirs, files in os.walk(dir_path):
                    curr_path = Path(root)
                    depth = len(curr_path.resolve().parts) - base_depth
                    if depth >= max_depth:
                        dirs.clear()
                        continue
                    if not show_hidden:
                        dirs[:] = [d for d in dirs if d not in IGNORED_NAMES]
                    rel_prefix = curr_path.relative_to(dir_path)
                    prefix_str = "" if str(rel_prefix) == "." else f"{rel_prefix}/"
                    for d in sorted(dirs):
                        entries.append(f"[DIR]  {prefix_str}{d}")
                    for f in sorted(files):
                        entries.append(f"[FILE] {prefix_str}{f}")

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output="\n".join(entries) if entries else "(empty directory)",
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
