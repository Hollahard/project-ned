"""Extra diagnostic tripwires, not a security sandbox for untrusted Python."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PolicyViolation(RuntimeError):
    """A diagnostic operation exceeded its audited subset."""


class DiagnosticPolicy:
    def __init__(self, state: Path, read_roots: list[Path]):
        self.state = state.resolve(strict=True)
        self.read_roots = [p.resolve(strict=True) for p in read_roots] + [self.state]
        self.violations: list[str] = []
        self.violation_locations: list[dict] = []

    def deny(self, event: str) -> None:
        self.violations.append(event)
        frame = sys._getframe(1)
        trace = []
        while frame is not None and len(trace) < 12:
            trace.append(
                {
                    "file": Path(frame.f_code.co_filename).name,
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                }
            )
            frame = frame.f_back
        self.violation_locations.append({"event": event, "trace": trace})
        raise PolicyViolation(event)

    def path(self, raw: object, *, write: bool = False) -> None:
        if isinstance(raw, int):
            return  # Already-open standard streams / owned sockets.
        p = Path(os.fsdecode(raw)).resolve()
        if p.name.lower().startswith(".env") or p.name.lower() in {
            "auth.json",
            "auth.yaml",
            "auth.yml",
            "host-serve.token",
            "host-gateway.token",
        }:
            self.deny("credential_file")
        roots = [self.state] if write else self.read_roots
        if not any(p.is_relative_to(root) for root in roots):
            self.deny("write_outside_state" if write else "read_outside_roots")

    def check(self, event: str, args: tuple) -> None:
        if event == "import":
            name = args[0]
            if name in {
                "hermes_bootstrap",
                "hermes_cli.main",
                "hermes_cli.web_server",
                "tui_gateway.server",
                "tui_gateway.entry",
                "run_agent",
            } or name.split(".")[0] in {
                "torch",
                "exllamav2",
                "exllamav3",
                "transformers",
            }:
                self.deny("blocked_import:" + name)
        elif event == "open":
            mode, flags = args[1], args[2]
            write = bool(
                flags
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            self.path(
                args[0], write=write or (bool(mode) and any(c in mode for c in "wax+"))
            )
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            self.path(args[0], write=True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            self.path(args[0], write=True)
            self.path(args[1], write=True)
        elif event == "sqlite3.connect":
            raw = str(args[0])
            if raw != ":memory:":
                if raw.startswith("file:"):
                    raw = (
                        unquote(urlsplit(raw).path).lstrip("/")
                        if os.name == "nt"
                        else unquote(urlsplit(raw).path)
                    )
                self.path(raw, write=True)
        elif event in {
            "sqlite3.load_extension",
            "subprocess.Popen",
            "os.system",
            "os.kill",
            "os.exec",
            "os.posix_spawn",
            "socket.connect",
            "socket.getaddrinfo",
        }:
            self.deny(event)
        elif event == "socket.bind":
            if args[1] != ("127.0.0.1", 0):
                self.deny(event)


def valid_token(value: str) -> bool:
    return 32 <= len(value) <= 4096 and all(33 <= ord(c) <= 126 for c in value)
