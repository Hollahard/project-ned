"""PowerShell AST analysis and security policy validator.

Defends against command injection, obfuscated scripts, and download cradles:
- -EncodedCommand / -enc base64 obfuscation
- Download cradles: Invoke-WebRequest, iwr, curl, wget, Invoke-RestMethod, irm, Net.WebClient, HttpClient, Start-BitsTransfer
- Dynamic evaluation: Invoke-Expression, iex, [ScriptBlock]::Create, & string/variable invocations
- Dangerous execution utilities: mshta, rundll32, regsvr32, certutil
- Backtick obfuscation (e.g. I`e`X)
- String concatenation / format operator dynamic evaluation
"""

import logging
import os
import re
import subprocess
import sys
from typing import List, Set

logger = logging.getLogger(__name__)


class PowerShellSecurityViolation(ValueError):
    """Raised when a command fails static or AST security inspection."""
    pass


class PowerShellASTValidator:
    """Multi-stage validator for PowerShell commands."""

    BLOCKED_COMMANDS: Set[str] = {
        "invoke-webrequest",
        "iwr",
        "wget",
        "curl",
        "invoke-restmethod",
        "irm",
        "invoke-expression",
        "iex",
        "start-bitstransfer",
        "bitsadmin",
        "mshta",
        "rundll32",
        "regsvr32",
        "certutil",
        "add-type",
    }

    BLOCKED_MEMBERS: Set[str] = {
        "downloadstring",
        "downloadfile",
        "downloaddata",
        "openread",
        "uploadstring",
        "uploadfile",
        "create",  # e.g. [scriptblock]::create
        "load",    # e.g. [System.Reflection.Assembly]::Load
        "loadfile",
        "loadfrom",
    }

    BLOCKED_TYPES: Set[str] = {
        "webclient",
        "system.net.webclient",
        "httpclient",
        "system.net.http.httpclient",
        "system.reflection.assembly",
        "system.runtime.interopservices.marshal",
    }

    ENCODED_FLAGS: Set[str] = {
        "-encodedcommand",
        "-enc",
        "-e",
        "-ec",
        "/encodedcommand",
        "/enc",
        "/e",
        "/ec",
    }

    @classmethod
    def normalize_backticks(cls, text: str) -> str:
        """Strip PowerShell backtick escape characters used for string/cmdlet obfuscation."""
        # In PowerShell, ` escapes the next character (e.g. I`e`X -> IeX)
        return re.sub(r"`", "", text)

    @classmethod
    def check_lexical(cls, command: str) -> None:
        """Fast lexical and pattern-based checks applied before AST parsing."""
        if not command or not command.strip():
            return

        normalized = cls.normalize_backticks(command)
        tokens = normalized.split()

        # 1. Check for encoded command flags (e.g. powershell -enc ...)
        for idx, token in enumerate(tokens):
            lower_token = token.lower().strip()
            for flag in cls.ENCODED_FLAGS:
                if lower_token == flag or lower_token.startswith(f"{flag}:") or lower_token.startswith(f"{flag}="):
                    raise PowerShellSecurityViolation(
                        f"Blocked encoded execution parameter: '{token}'"
                    )
            # Check for ExecutionPolicy bypass flags
            if lower_token in ("-executionpolicy", "/executionpolicy", "-ep", "/ep"):
                if idx + 1 < len(tokens) and tokens[idx + 1].lower() in ("bypass", "unrestricted"):
                    raise PowerShellSecurityViolation(
                        f"Blocked execution policy bypass parameter: '{token} {tokens[idx + 1]}'"
                    )
            elif lower_token.startswith("-executionpolicy:") or lower_token.startswith("-ep:"):
                if "bypass" in lower_token or "unrestricted" in lower_token:
                    raise PowerShellSecurityViolation(
                        f"Blocked execution policy bypass parameter: '{token}'"
                    )

        # 2. Check for blocked command names / aliases
        # Extract command-like identifiers
        words = re.findall(r"[a-zA-Z0-9_\-\.\:]+", normalized)
        for word in words:
            lower_word = word.lower()
            base_word = lower_word[:-4] if lower_word.endswith(".exe") else lower_word
            if lower_word in cls.BLOCKED_COMMANDS or base_word in cls.BLOCKED_COMMANDS:
                raise PowerShellSecurityViolation(
                    f"Blocked command or cmdlet detected: '{word}'"
                )

        # 3. Check for blocked method/member invocations (e.g. .DownloadString(...), ::Create(...))
        for member in cls.BLOCKED_MEMBERS:
            pattern = rf"(?:\.|\:\:)\s*{re.escape(member)}\s*(?:\(|$|\s)"
            if re.search(pattern, normalized, re.IGNORECASE):
                raise PowerShellSecurityViolation(
                    f"Blocked member invocation detected: '{member}'"
                )

        # 4. Check for blocked .NET types
        for tname in cls.BLOCKED_TYPES:
            pattern = rf"\[\s*{re.escape(tname)}\s*\]"
            if re.search(pattern, normalized, re.IGNORECASE):
                raise PowerShellSecurityViolation(
                    f"Blocked .NET type reference detected: '[{tname}]'"
                )

        # 5. Check for dynamic string concatenation invocation e.g. & ('i'+'ex') or & ("inv"+"oke-expression")
        if re.search(r"&\s*\(\s*['\"][^'\"]*['\"]\s*\+", normalized):
            raise PowerShellSecurityViolation(
                "Blocked dynamic string concatenation invocation operator"
            )

        # 6. Check for format operator invocation e.g. & ("{0}{1}" -f ...)
        if re.search(r"&\s*\([^)]*-f[^)]*\)", normalized, re.IGNORECASE):
            raise PowerShellSecurityViolation(
                "Blocked format operator dynamic invocation"
            )

        # 7. Check for certutil download cradle pattern
        if "certutil" in normalized.lower() and ("urlcache" in normalized.lower() or "-f" in normalized.lower()):
            raise PowerShellSecurityViolation(
                "Blocked certutil download cradle invocation"
            )

    @classmethod
    def check_powershell_ast_win32(cls, command: str) -> None:
        """Deep AST validation via Windows PowerShell parser."""
        if sys.platform != "win32":
            return

        # Power shell parser script inspecting AST nodes via stdin
        parser_ps = r"""
$input_text = [Console]::In.ReadToEnd()
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($input_text, [ref]$tokens, [ref]$errors)

$error_msgs = @()
if ($errors -and $errors.Count -gt 0) {
    foreach ($err in $errors) {
        $error_msgs += $err.Message
    }
}

$cmd_names = @()
$ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object {
    $name = $_.GetCommandName()
    if ($name) { $cmd_names += $name }
}

$member_names = @()
$ast.FindAll({ $args[0] -is [System.Management.Automation.Language.MemberExpressionAst] -or $args[0] -is [System.Management.Automation.Language.InvokeMemberExpressionAst] }, $true) | ForEach-Object {
    if ($_.Member) {
        $member_names += $_.Member.Value
    }
}

$type_names = @()
$ast.FindAll({ $args[0] -is [System.Management.Automation.Language.TypeExpressionAst] }, $true) | ForEach-Object {
    if ($_.TypeName) {
        $type_names += $_.TypeName.FullName
    }
}

@{
    errors = $error_msgs
    commands = $cmd_names
    members = $member_names
    types = $type_names
} | ConvertTo-Json -Compress
"""

        try:
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parser_ps],
                input=command,
                text=True,
                capture_output=True,
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Windows PowerShell AST parser execution skipped or failed: %s", exc)
            return

        if res.returncode != 0:
            logger.warning("PowerShell AST parser returned non-zero (%d): %s", res.returncode, res.stderr)
            return

        out = res.stdout.strip()
        if not out:
            return

        import json
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return

        errors = data.get("errors") or []
        if errors:
            raise PowerShellSecurityViolation(
                f"PowerShell AST syntax error or parsing violation: {errors[0]}"
            )

        commands = data.get("commands") or []
        if isinstance(commands, str):
            commands = [commands]
        for cmd in commands:
            cmd_norm = cls.normalize_backticks(cmd).lower()
            cmd_base = cmd_norm[:-4] if cmd_norm.endswith(".exe") else cmd_norm
            if cmd_norm in cls.BLOCKED_COMMANDS or cmd_base in cls.BLOCKED_COMMANDS:
                raise PowerShellSecurityViolation(
                    f"Blocked command detected via AST: '{cmd}'"
                )

        members = data.get("members") or []
        if isinstance(members, str):
            members = [members]
        for mem in members:
            mem_norm = cls.normalize_backticks(mem).lower()
            if mem_norm in cls.BLOCKED_MEMBERS:
                raise PowerShellSecurityViolation(
                    f"Blocked member invocation detected via AST: '{mem}'"
                )

        types = data.get("types") or []
        if isinstance(types, str):
            types = [types]
        for t in types:
            t_norm = cls.normalize_backticks(t).lower()
            for blocked_t in cls.BLOCKED_TYPES:
                if blocked_t in t_norm:
                    raise PowerShellSecurityViolation(
                        f"Blocked .NET type reference detected via AST: '{t}'"
                    )

    @classmethod
    def validate_script(cls, command: str) -> None:
        """Comprehensive verification of PowerShell command string."""
        cls.check_lexical(command)
        cls.check_powershell_ast_win32(command)
