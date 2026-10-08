"""Synthetic protocol fixture. No CUDA, model files, inference libraries, or external traffic."""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--model", required=True)
args = parser.parse_args()
api_key = os.environ.pop("HERMES_TABBY_API_KEY")
admin_key = os.environ.pop("HERMES_TABBY_ADMIN_KEY")
loaded = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value, *, sse=False):
        data = value.encode() if sse else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        global loaded
        carriers = [
            (name, value)
            for name, value in self.headers.items()
            if name.lower() in ("authorization", "x-api-key", "x-admin-key")
        ]
        value = carriers[0][1] if len(carriers) == 1 else ""
        role = (
            "admin"
            if value == f"Bearer {admin_key}"
            else "api"
            if value == f"Bearer {api_key}"
            else None
        )
        if role is None or (
            self.path in ("/v1/model/load", "/v1/model/unload") and role != "admin"
        ):
            self.reply(401, {})
            return
        if self.path == "/v1/auth/permission":
            self.reply(200, {"permission": role})
        elif self.path == "/v1/model/load":
            loaded = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.reply(
                200,
                'data: {"model_type":"model","module":1,"modules":1,"status":"finished"}\n\n',
                sse=True,
            )
        elif self.path == "/v1/model/unload":
            loaded = None
            self.reply(200, {})
        elif not loaded:
            self.reply(503, {"detail": "No models are currently loaded."})
        elif self.path == "/v1/model":
            p = loaded
            self.reply(
                200,
                {
                    "id": Path(args.model).name,
                    "parameters": {
                        "max_seq_len": p["max_seq_len"],
                        "cache_size": p["cache_size"],
                        "cache_mode": p["cache_mode"],
                        "max_batch_size": p["max_batch_size"],
                        "chunk_size": p["chunk_size"],
                        "use_vision": p["vision"],
                        "draft": None,
                        "hermes_native_draft_enabled": False,
                    },
                },
            )
        elif self.path == "/props":
            self.reply(
                200,
                {
                    "model_path": args.model,
                    "total_slots": loaded["max_batch_size"],
                    "default_generation_settings": {"n_ctx": loaded["max_seq_len"]},
                    "modalities": {"vision": loaded["vision"]},
                },
            )
        elif self.path == "/v1/completions":
            self.rfile.read(int(self.headers["Content-Length"]))
            self.reply(
                200,
                {
                    "choices": [{"text": " fixture text", "finish_reason": "stop"}],
                    "usage": {"completion_tokens": 2},
                },
            )
        else:
            self.reply(404, {})

    do_GET = dispatch
    do_POST = dispatch


server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
(args.root / "bootstrap-proof.json").write_text(json.dumps({"pid": os.getpid()}))
server.serve_forever()
