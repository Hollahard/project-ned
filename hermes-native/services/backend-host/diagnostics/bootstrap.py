"""Explicit managed HTTP diagnostic. Never invoke stock Hermes entrypoints."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hermes_backend_host.diagnostic_policy import (  # noqa: E402
    DiagnosticPolicy,
    valid_token,
)
from hermes_backend_host.diagnostic_source import verify  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state = args.state.resolve(strict=True)
    if not Path.cwd().samefile(state) or not Path(os.environ["HERMES_HOME"]).samefile(
        state
    ):
        raise ValueError("Synthetic home must equal working directory")
    token = os.environ.pop("HERMES_DIAGNOSTIC_SESSION_TOKEN", "")
    if not valid_token(token):
        raise ValueError("Missing or invalid environment-only diagnostic token")
    if tuple(state.iterdir()):
        raise ValueError("Diagnostic state must be newly created and empty")
    candidate = args.candidate.resolve(strict=True)
    manifest = verify(candidate)
    manifest_hash = hashlib.sha256(
        (candidate / "source-manifest.json").read_bytes()
    ).hexdigest()
    root = candidate / "source"
    site = args.site_packages.resolve(strict=True)
    sys.path[:0] = [
        str(root),
        str(site),
    ]  # No site.main(), .pth execution, editable imports.
    policy = DiagnosticPolicy(
        state, [root, site, Path(sys.base_prefix), Path(__file__).resolve().parents[1]]
    )
    sys.addaudithook(policy.check)
    logging.disable(
        logging.CRITICAL
    )  # This diagnostic exports structured, non-content evidence only.
    phase = "imports"
    try:
        import uvicorn
        from fastapi import FastAPI
        from hermes_cli.web_routers.config_env import get_config
        from hermes_cli.web_routers.sessions import get_sessions
        from hermes_state import SessionDB
        from starlette.responses import JSONResponse

        if policy.violations:
            raise RuntimeError("Import closure exceeded policy")
        phase = "database"
        with_db = SessionDB(db_path=state / "state.db")
        try:
            with_db.create_session(
                "managed-diagnostic-session",
                "cli",
                model="diagnostic/no-inference",
            )
            with_db.set_session_title(
                "managed-diagnostic-session", "Managed diagnostic session"
            )
        finally:
            with_db.close()
        if policy.violations:
            raise RuntimeError("Audited subset exceeded policy")
        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        app.add_api_route("/api/config", get_config, methods=["GET"])
        app.add_api_route("/api/sessions", get_sessions, methods=["GET"])

        @app.get("/diagnostic/identity")
        async def identity():
            return {
                "mode": manifest["mode"],
                "pid": os.getpid(),
                "source_manifest_sha256": manifest_hash,
                "source_files": len(manifest["source_files"]),
                "retained_handlers": manifest["retained_handlers"],
                "loaded_project_modules": sorted(
                    n
                    for n, m in sys.modules.copy().items()
                    if getattr(m, "__file__", None)
                    and Path(m.__file__).is_relative_to(root)
                ),
                "thread_names": sorted(t.name for t in threading.enumerate()),
                "environment_names": sorted(os.environ),
                "policy_violations": policy.violations,
            }

        class Boundary:
            def __init__(self, inner):
                self.inner = inner

            async def __call__(self, scope, receive, send):
                if scope["type"] == "lifespan":
                    return await self.inner(scope, receive, send)
                if scope["type"] != "http":
                    return await send({"type": "websocket.close", "code": 1008})
                headers = [
                    v
                    for k, v in scope["headers"]
                    if k.lower() == b"x-hermes-session-token"
                ]
                authorized = len(headers) == 1 and hmac.compare_digest(
                    headers[0], token.encode("ascii")
                )
                if not authorized:
                    response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                elif policy.violations:
                    response = JSONResponse(
                        {"detail": "Diagnostic policy violated"}, status_code=503
                    )
                elif scope["method"] != "GET" or scope["path"] not in {
                    "/api/config",
                    "/api/sessions",
                    "/diagnostic/identity",
                }:
                    response = JSONResponse(
                        {"detail": "Outside diagnostic subset"}, status_code=403
                    )
                elif "profile" in parse_qs(
                    scope["query_string"].decode("ascii", "replace"),
                    keep_blank_values=True,
                ):
                    response = JSONResponse(
                        {"detail": "Named profile routing disabled"}, status_code=403
                    )
                else:
                    try:
                        return await self.inner(scope, receive, send)
                    except BaseException as exc:
                        (state / "diagnostic-failure.json").write_text(
                            json.dumps(
                                {
                                    "phase": "request:" + scope["path"],
                                    "error_type": type(exc).__name__,
                                    "policy_violations": policy.violations,
                                    "violation_locations": policy.violation_locations,
                                    "trace": [
                                        {
                                            "file": Path(
                                                f.tb_frame.f_code.co_filename
                                            ).name,
                                            "function": f.tb_frame.f_code.co_name,
                                            "line": f.tb_lineno,
                                        }
                                        for f in traceback_frames(exc.__traceback__)
                                    ],
                                }
                            ),
                            encoding="utf-8",
                        )
                        raise
                await response(scope, receive, send)

        phase = "listen"

        async def serve():
            # Uvicorn's existing-socket branch calls platform.system() even for one
            # worker. Its normal numeric-host/port=0 branch avoids that subprocess
            # fallback; observe the actual bound socket after startup instead.
            config = uvicorn.Config(
                Boundary(app),
                host="127.0.0.1",
                port=0,
                access_log=False,
                log_config=None,
                lifespan="off",
                loop="none",
                ws="none",
                http="h11",
            )
            server = uvicorn.Server(config)
            worker = asyncio.create_task(server.serve())
            for _ in range(200):
                if worker.done():
                    await worker
                    raise RuntimeError("Server exited before readiness")
                if server.started:
                    sock = server.servers[0].sockets[0]
                    if sock.getsockname()[0] != "127.0.0.1":
                        raise RuntimeError("Unexpected listening interface")
                    os.write(
                        1,
                        f"HERMES_BACKEND_READY port={sock.getsockname()[1]}\n".encode(),
                    )
                    break
                await asyncio.sleep(0.01)
            else:
                raise TimeoutError("Server startup deadline")
            await worker

        asyncio.get_event_loop().run_until_complete(serve())
    except BaseException as exc:
        (state / "diagnostic-failure.json").write_text(
            json.dumps(
                {
                    "phase": phase,
                    "error_type": type(exc).__name__,
                    "policy_violations": policy.violations,
                    "violation_locations": policy.violation_locations,
                    "trace": [
                        {
                            "file": Path(f.tb_frame.f_code.co_filename).name,
                            "function": f.tb_frame.f_code.co_name,
                            "line": f.tb_lineno,
                        }
                        for f in traceback_frames(exc.__traceback__)
                    ],
                }
            ),
            encoding="utf-8",
        )
        raise SystemExit(2) from None


def traceback_frames(tb):
    while tb is not None:
        yield tb
        tb = tb.tb_next


if __name__ == "__main__":
    # This diagnostic's event loop is created before audit installation; no upstream code
    # runs here. It avoids allowing network-connect audit exceptions for asyncio internals.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        main()
    finally:
        loop.close()
