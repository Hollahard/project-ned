"""Environment-only authentication for the dedicated Hermes TabbyAPI pack.

This maintained replacement preserves Tabby's imported authentication entry
points. It intentionally has no token-file generation, watcher or auth-off mode.
"""

import hmac
import logging
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)
API_KEY_ENV = "HERMES_TABBY_API_KEY"
ADMIN_KEY_ENV = "HERMES_TABBY_ADMIN_KEY"


@dataclass(frozen=True, repr=False)
class AuthKeys:
    api_key: str
    admin_key: str

    def verify_key(self, test_key: str, key_type: str) -> bool:
        if (
            not isinstance(test_key, str)
            or not test_key.isascii()
            or len(test_key) > 4096
        ):
            return False
        admin = hmac.compare_digest(test_key, self.admin_key)
        api = hmac.compare_digest(test_key, self.api_key)
        return (
            admin
            if key_type == "admin_key"
            else (admin or api)
            if key_type == "api_key"
            else False
        )


AUTH_KEYS: AuthKeys | None = None
# Compatibility symbol only. Nothing in this module grants auth-free access.
DISABLE_AUTH = False


def _required_key(name: str) -> str:
    value = os.environ.get(name, "")
    if not (32 <= len(value) <= 4096) or any(not 0x21 <= ord(c) <= 0x7E for c in value):
        raise RuntimeError(
            f"{name} must contain 32 to 4096 printable ASCII characters without whitespace"
        )
    return value


async def load_auth_keys(disable_from_config: bool) -> None:
    """Initialize before listening. Rotation requires an owned worker restart."""
    global AUTH_KEYS
    AUTH_KEYS = None
    if disable_from_config:
        raise RuntimeError(
            "Authentication cannot be disabled in the managed Hermes runtime"
        )
    api_key = _required_key(API_KEY_ENV)
    admin_key = _required_key(ADMIN_KEY_ENV)
    if hmac.compare_digest(api_key, admin_key):
        raise RuntimeError(
            "Managed inference and administrative tokens must be different"
        )
    AUTH_KEYS = AuthKeys(api_key, admin_key)
    # Remove only our dedicated worker secrets after consumption, limiting
    # inheritance into children. The coordinator retains its own scoped copy.
    os.environ.pop(API_KEY_ENV, None)
    os.environ.pop(ADMIN_KEY_ENV, None)
    logger.info("Managed runtime authentication initialized from environment")


def _token(request: Request) -> str:
    # Reading raw ASGI headers preserves duplicate occurrences. Header mapping
    # lookups may select one value and hide a conflicting credential. Empty
    # carriers count too: one valid credential plus an empty second is ambiguous.
    carriers = [
        (name.lower(), value)
        for name, value in request.scope.get("headers", [])
        if name.lower() in {b"x-api-key", b"x-admin-key", b"authorization"}
    ]
    if len(carriers) != 1:
        raise HTTPException(401, "Provide exactly one authentication credential")
    name, raw = carriers[0]
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(401, "Malformed authentication credential") from None
    if any(not 0x20 <= ord(c) <= 0x7E for c in value):
        raise HTTPException(401, "Malformed authentication credential")
    if name == b"authorization":
        pieces = value.split()
        if len(pieces) != 2 or pieces[0].lower() != "bearer":
            raise HTTPException(401, "Malformed authentication credential")
        value = pieces[1]
    if not value or any(not 0x21 <= ord(c) <= 0x7E for c in value):
        raise HTTPException(401, "Malformed authentication credential")
    return value


def get_key_permission(request: Request) -> str:
    """Return the same role names consumed by the pinned upstream routers."""
    auth_keys = AUTH_KEYS
    if auth_keys is None:
        raise HTTPException(503, "Runtime authentication is not initialized")
    value = _token(request)
    if auth_keys.verify_key(value, "admin_key"):
        return "admin"
    if auth_keys.verify_key(value, "api_key"):
        return "api"
    raise HTTPException(401, "Invalid authentication credential")


def _authorize(request: Request, role: str) -> str:
    auth_keys = AUTH_KEYS
    if auth_keys is None:
        raise HTTPException(503, "Runtime authentication is not initialized")
    token = _token(request)
    if not auth_keys.verify_key(token, role):
        raise HTTPException(401, "Invalid authentication credential")
    return token


async def check_api_key(request: Request) -> str:
    return _authorize(request, "api_key")


async def check_admin_key(request: Request) -> str:
    return _authorize(request, "admin_key")
