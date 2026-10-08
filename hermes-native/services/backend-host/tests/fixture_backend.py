"""Harmless standard-library HTTP child. Never imports Hermes or inference code."""

import ctypes
import hmac
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mode = sys.argv[1] if len(sys.argv) > 1 else "good"
if mode == "exit":
    raise SystemExit(7)
if mode == "silent":
    time.sleep(60)
    raise SystemExit(0)
if mode == "malformed":
    print("HERMES_BACKEND_READY port=0", flush=True)
    time.sleep(60)
    raise SystemExit(0)
if mode == "oversize":
    os.write(1, b"x" * 65536)
    time.sleep(60)
    raise SystemExit(0)
if mode == "flood":
    os.write(2, b"x" * 262144)
if mode == "descendant":
    subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        env={"SystemRoot": os.environ["SystemRoot"]},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected = os.environ["FIXTURE_SESSION_TOKEN"]
        provided = self.headers.get("X-Hermes-Session-Token", "")
        if not hmac.compare_digest(provided, expected):
            self.answer(401, {"detail": "Fixture authentication required"})
            return
        if self.path == "/api/config":
            self.answer(
                200,
                {
                    "model": {"default": "fixture-unloaded"},
                    "display": {"resume_last_session": False},
                },
            )
        elif self.path == "/api/sessions":
            self.answer(200, {"sessions": [], "total": 0})
        elif self.path == "/api/identity":
            unlisted = os.environ.get("UNLISTED_HANDLE")
            inherited = None
            if unlisted:
                get_info = ctypes.WinDLL(
                    "kernel32", use_last_error=True
                ).GetHandleInformation
                get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
                get_info.restype = ctypes.c_int
                flags = ctypes.c_ulong()
                inherited = bool(get_info(int(unlisted), ctypes.byref(flags)))
            self.answer(
                200,
                {
                    "pid": os.getpid(),
                    "cwd": os.getcwd(),
                    "home": os.environ.get("HERMES_HOME"),
                    "environment_names": sorted(os.environ),
                    "arguments": sys.argv[2:],
                    "stdin_eof": sys.stdin.read(1) == "",
                    "unlisted_handle_inherited": inherited,
                },
            )
        else:
            self.answer(404, {"detail": "Fixture endpoint not found"})

    def answer(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
for line in [
    f"HERMES_BACKEND_READY port={port}\n",
    f"HERMES_DASHBOARD_READY port={port}\r\n",
]:
    # Chunk at arbitrary boundaries to exercise the capture/parser seam.
    for offset in range(0, len(line), 7):
        os.write(1, line[offset : offset + 7].encode())
server.serve_forever(poll_interval=0.05)
