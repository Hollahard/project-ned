"""Bind each HTTP connection to an observed server socket in our private Job."""

from __future__ import annotations

import ctypes
import http.client
import json as json_module
import socket
import struct
from dataclasses import dataclass


def established_server_pids(
    local: tuple[str, int], remote: tuple[str, int]
) -> list[int]:
    """IPv4 TCP owner snapshot, scoped to one exact established connection."""
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    api.restype = ctypes.c_ulong
    size = ctypes.c_ulong()
    # AF_INET=2, TCP_TABLE_OWNER_PID_ALL=5; query only, never acquire kill handles.
    if api(None, ctypes.byref(size), False, 2, 5, 0) not in (0, 122):
        raise RuntimeError("TCP ownership size query failed")
    for _ in range(3):
        if not 4 <= size.value <= 64 * 1024 * 1024:
            raise RuntimeError("TCP ownership table size exceeded bound")
        buffer = ctypes.create_string_buffer(size.value)
        status = api(buffer, ctypes.byref(size), False, 2, 5, 0)
        if status == 122:
            continue
        if status:
            raise RuntimeError("TCP ownership query failed")
        count = struct.unpack_from("<I", buffer.raw)[0]
        if 4 + count * 24 > len(buffer):
            raise RuntimeError("TCP ownership table truncated")
        found = []
        for index in range(count):
            state, address, port, peer, peer_port, pid = struct.unpack_from(
                "<6I", buffer.raw, 4 + index * 24
            )
            endpoint = (
                socket.inet_ntoa(struct.pack("<I", address)),
                socket.ntohs(port & 0xFFFF),
            )
            other = (
                socket.inet_ntoa(struct.pack("<I", peer)),
                socket.ntohs(peer_port & 0xFFFF),
            )
            if state == 5 and endpoint == local and other == remote:
                found.append(pid)
        return found
    raise RuntimeError("TCP ownership table kept changing")


class _Connection(http.client.HTTPConnection):
    def __init__(self, process, port: int, timeout: float):
        super().__init__("127.0.0.1", port, timeout=timeout)
        self.process = process

    def verify_owner(self):
        if self.sock is None or self.process.poll() is not None:
            raise RuntimeError("Owned backend has no live connection")
        owners = established_server_pids(
            self.sock.getpeername(), self.sock.getsockname()
        )
        if len(owners) != 1 or not self.process.contains_observed_pid(owners[0]):
            self.close()
            raise RuntimeError("Established server socket is not owned by backend Job")

    def connect(self):
        super().connect()  # A TCP handshake carries no HTTP credential bytes.
        try:
            self.verify_owner()
        except BaseException:
            self.close()
            raise


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes

    def json(self):
        return json_module.loads(self.body)


class OwnedHTTPClient:
    def __init__(self, process, port: int, timeout: float = 15):
        self.connection = _Connection(process, port, timeout)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()

    def request(self, method: str, path: str, *, headers=(), json=None):
        connection = self.connection
        if connection.sock is not None:
            connection.verify_owner()
        else:
            connection.connect()
        items = headers.items() if isinstance(headers, dict) else headers
        body = None if json is None else json_module.dumps(json).encode("utf-8")
        connection.putrequest(method, path)
        for key, value in items:
            connection.putheader(key, value)
        if body is not None:
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            connection.close()
            raise RuntimeError("HTTP diagnostic response exceeded bound")
        return Response(response.status, payload)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)
