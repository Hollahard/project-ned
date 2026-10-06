"""PowerShell terminal execution tool with Constrained Language Mode and AST validation (Risk 2)."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.security.paths import is_path_within_root
from friday.security.powershell import PowerShellASTValidator, PowerShellSecurityViolation
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

SAFE_ENV_WHITELIST = {
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "COMSPEC",
    "WINDIR",
    "USERNAME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "SYSTEMDRIVE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "APPDATA",
    "LOCALAPPDATA",
    "PATHEXT",
    "PSMODULEPATH",
}


class TerminalExecTool(Tool):
    """Executes validated commands via PowerShell in Constrained Language Mode within safe workspace roots."""

    name = "terminal.exec"
    description = (
        "Execute a terminal command via PowerShell in Constrained Language Mode within the workspace. "
        "Strictly gated by native OS approval and static AST validation."
    )
    risk_level = 2
    requires_approval = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command or script to execute"},
            "working_dir": {
                "type": "string",
                "description": "Working directory path within the safe workspace root",
                "default": ".",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum execution time in seconds (1-300)",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def __init__(self, safe_roots: Optional[List[Path]] = None) -> None:
        self.safe_roots = safe_roots or [Path.cwd()]

    @classmethod
    def get_sanitized_env(cls) -> Dict[str, str]:
        """Construct child process environment containing strictly whitelisted variables."""
        return {
            k: v
            for k, v in os.environ.items()
            if k.upper() in SAFE_ENV_WHITELIST
        }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        command = str(arguments["command"]).strip()
        working_dir_raw = arguments.get("working_dir") or (str(self.safe_roots[0]) if self.safe_roots else ".")
        timeout_seconds = min(300, max(1, int(arguments.get("timeout_seconds", 30))))

        # 1. Static and AST security inspection
        try:
            PowerShellASTValidator.validate_script(command)
        except PowerShellSecurityViolation as viol:
            logger.warning("Terminal command rejected by AST validator: %s", viol)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Security policy violation: {viol}",
            )

        # 2. Verify working directory containment
        cwd_path = Path(working_dir_raw).resolve()
        if self.safe_roots and not any(is_path_within_root(cwd_path, root) for root in self.safe_roots):
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Working directory is outside configured safe roots: {cwd_path}",
            )

        # 3. Environment sanitization
        env = self.get_sanitized_env()

        # 4. Formulate command execution in Constrained Language Mode
        if sys.platform == "win32":
            ps_script = (
                "$ErrorActionPreference = 'Stop'; "
                "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; "
                f"& {{ {command} }}"
            )
            exec_args = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ]
        else:
            # Fallback for cross-platform test environments
            exec_args = ["bash", "-c", command]

        # 5. Process execution inside async subprocess
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Execution timed out after {timeout_seconds} seconds",
                )

            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            clm_violation = bool(
                stderr_str
                and (
                    "LanguageMode" in stderr_str
                    or "Cannot invoke method" in stderr_str
                    or "MethodInvocationNotSupported" in stderr_str
                )
            )
            success = (proc.returncode == 0) and not clm_violation
            output = stdout_str if stdout_str else ("(no output)" if success else "")
            error_output = stderr_str if not success else None
            if not success and not error_output:
                error_output = f"Execution failed with return code {proc.returncode}"

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=success,
                output=output,
                error=error_output,
                metadata={
                    "returncode": proc.returncode,
                    "command": command,
                    "working_dir": str(cwd_path),
                },
            )
        except Exception as exc:
            logger.error("Terminal execution failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Process invocation error: {exc}",
            )
