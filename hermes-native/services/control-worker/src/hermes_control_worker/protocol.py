"""Strict finite JSONL control service; no engine, process or network operations."""

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import BinaryIO

from . import PROTOCOL, SERVICE
from .errors import ControlError
from .profiles import ProfileStore, exact_params, profile_schema, validate_profile

logger = logging.getLogger(__name__)
MAX_FRAME = 65_536  # Includes the mandatory final LF.
MAX_REQUESTS = 4096
REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z", re.ASCII)
METHODS = (
    "service.describe",
    "runtime.status",
    "profiles.schema",
    "profiles.validate",
    "profiles.list",
    "profiles.get",
    "profiles.save",
    "profiles.delete",
    "service.shutdown",
)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("Nonfinite value")


def _send(stream: BinaryIO, payload: dict) -> None:
    data = (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n"
    )
    if len(data) > MAX_FRAME:
        raise ControlError("RESPONSE_LIMIT", "The control response exceeded its byte limit.")
    stream.write(data)
    stream.flush()


def _error(stream: BinaryIO, request_id: str | None, code: str, message: str) -> None:
    _send(stream, {"id": request_id, "error": {"code": code, "message": message}})


def dispatch(store: ProfileStore, method: str, params: object) -> dict:
    if method in (
        "service.describe",
        "runtime.status",
        "profiles.schema",
        "profiles.list",
        "service.shutdown",
    ):
        exact_params(params, set())
    if method == "service.describe":
        return {
            "protocol": PROTOCOL,
            "service": SERVICE,
            "methods": list(METHODS),
            "max_frame_bytes": MAX_FRAME,
            "max_requests": MAX_REQUESTS,
            "runtime_attached": False,
            "admission_allowed": False,
        }
    if method == "runtime.status":
        return {
            "state": "detached",
            "runtime_attached": False,
            "admission_allowed": False,
            "active_profile": None,
            "engine_observed": False,
        }
    if method == "profiles.schema":
        return profile_schema()
    if method == "profiles.validate":
        values = exact_params(params, {"profile"})
        return {
            "profile": validate_profile(values["profile"]),
            "validation_scope": "schema",
            "artifact_verified": False,
        }
    if method == "profiles.list":
        return store.list_profiles()
    if method == "profiles.get":
        return store.get(params)
    if method == "profiles.save":
        return store.save(params)
    if method == "profiles.delete":
        return store.delete(params)
    if method == "service.shutdown":
        return {"stopping": True}
    raise ControlError("METHOD_UNAVAILABLE", "This control operation is unavailable.")


def serve(state: Path, incoming: BinaryIO, outgoing: BinaryIO) -> int:
    store = ProfileStore(state)
    seen = set()
    try:
        _send(
            outgoing,
            {"type": "ready", "protocol": PROTOCOL, "service": SERVICE, "runtime_attached": False},
        )
        logger.info("Control worker ready; inference remains detached.")
        while True:
            line = incoming.readline(MAX_FRAME + 1)
            if not line:
                logger.info("Control input closed.")
                return 0
            if len(line) > MAX_FRAME or not line.endswith(b"\n") or b"\r" in line:
                _error(
                    outgoing, None, "FRAME_INVALID", "Expected a bounded complete LF JSON frame."
                )
                return 2
            try:
                value = json.loads(
                    line.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
                )
                if type(value) is not dict or set(value) != {"id", "method", "params"}:
                    raise ValueError("Invalid envelope")
                request_id, method, params = value["id"], value["method"], value["params"]
                if type(request_id) is not str or REQUEST_ID.fullmatch(request_id) is None:
                    raise ValueError("Invalid request ID")
                if type(method) is not str or len(method) > 64 or type(params) is not dict:
                    raise ValueError("Invalid method or params")
            except (UnicodeError, ValueError, RecursionError):
                _error(
                    outgoing, None, "REQUEST_INVALID", "The control request envelope is invalid."
                )
                return 2
            if request_id in seen:
                _error(
                    outgoing,
                    request_id,
                    "DUPLICATE_ID",
                    "Each request ID must be unique per worker.",
                )
                continue
            if len(seen) >= MAX_REQUESTS:
                _error(
                    outgoing, request_id, "SESSION_LIMIT", "Restart the control worker to continue."
                )
                return 2
            seen.add(request_id)
            try:
                result = dispatch(store, method, params)
                _send(outgoing, {"id": request_id, "result": result})
            except ControlError as error:
                _error(outgoing, request_id, error.code, str(error))
                logger.info("Control request rejected: %s", error.code)
                continue
            except (sqlite3.Error, OSError, ValueError, TypeError):
                _error(
                    outgoing,
                    request_id,
                    "STATE_INVALID",
                    "The saved profile state is unavailable or invalid.",
                )
                logger.error("Control profile storage operation failed.")
                return 2
            if method == "service.shutdown":
                logger.info("Control worker stopped cooperatively.")
                return 0
    finally:
        store.close()
