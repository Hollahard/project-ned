"""Parse only complete, bounded machine-ready lines; never expose child logs."""

import re
import threading

_READY = re.compile(rb"HERMES_(?:BACKEND|DASHBOARD)_READY port=([0-9]{1,5})")


class ReadinessError(RuntimeError):
    pass


class ReadinessParser:
    def __init__(self, max_line: int = 16_384, max_bytes: int = 2_097_152):
        if max_line < 64 or max_bytes < max_line:
            raise ValueError("Invalid readiness bounds")
        self.max_line, self.max_bytes = max_line, max_bytes
        self._partial = bytearray()
        self._bytes = 0
        self._port = None
        self._error = None
        self._lock = threading.Lock()
        self.changed = threading.Event()

    def feed(self, data: bytes) -> None:
        with self._lock:
            if self._error:
                return
            self._bytes += len(data)
            if self._bytes > self.max_bytes:
                self._fail("Child output exceeded the readiness byte bound")
                return
            self._partial.extend(data)
            while b"\n" in self._partial:
                line, _, rest = self._partial.partition(b"\n")
                self._partial = bytearray(rest)
                if len(line) > self.max_line:
                    self._fail("Child output exceeded the readiness line bound")
                    return
                line = bytes(line).removesuffix(b"\r")
                match = _READY.fullmatch(line)
                if match:
                    port = int(match[1])
                    if not 1 <= port <= 65535:
                        self._fail("Child announced an invalid port")
                        return
                    if self._port is not None and self._port != port:
                        self._fail("Child announced conflicting ports")
                        return
                    self._port = port
                    self.changed.set()
                elif line.startswith(
                    (b"HERMES_BACKEND_READY", b"HERMES_DASHBOARD_READY")
                ):
                    self._fail("Child emitted a malformed readiness line")
                    return
            if len(self._partial) > self.max_line:
                self._fail("Child output exceeded the readiness line bound")

    def eof(self) -> None:
        with self._lock:
            if self._port is None and self._error is None:
                self._fail("Child stdout ended before a complete readiness line")

    def _fail(self, message: str) -> None:
        self._error = message
        self._partial.clear()
        self.changed.set()

    def port(self) -> int | None:
        with self._lock:
            if self._error:
                raise ReadinessError(self._error)
            return self._port
