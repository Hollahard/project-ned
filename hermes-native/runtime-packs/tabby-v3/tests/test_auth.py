import ast
import importlib.util
import logging
import secrets
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from starlette.requests import Request

from build_overlay import SAFE_REQUEST_LOG

SOURCE = Path(__file__).parents[1] / "overlay/common/auth.py"
spec = importlib.util.spec_from_file_location("hermes_pack_auth_under_test", SOURCE)
auth = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auth
spec.loader.exec_module(auth)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    auth.AUTH_KEYS = None
    monkeypatch.delenv(auth.API_KEY_ENV, raising=False)
    monkeypatch.delenv(auth.ADMIN_KEY_ENV, raising=False)


@pytest.fixture
async def credentials(monkeypatch, caplog):
    api, admin = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv(auth.API_KEY_ENV, api)
    monkeypatch.setenv(auth.ADMIN_KEY_ENV, admin)
    with caplog.at_level(logging.INFO):
        await auth.load_auth_keys(False)
    assert api not in caplog.text and admin not in caplog.text
    assert api not in repr(auth.AUTH_KEYS) and admin not in repr(auth.AUTH_KEYS)
    return api, admin


def app():
    application = FastAPI()
    application.state.permission_calls = 0

    @application.get("/inference", dependencies=[Depends(auth.check_api_key)])
    async def inference():
        return {"authorized": True}

    @application.post("/admin", dependencies=[Depends(auth.check_admin_key)])
    async def admin():
        return {"authorized": True}

    @application.get("/permission", dependencies=[Depends(auth.check_api_key)])
    async def permission(request: Request):
        application.state.permission_calls += 1
        return {"permission": auth.get_key_permission(request)}

    return application


@pytest.mark.asyncio
async def test_actual_fastapi_dependencies_enforce_roles(credentials):
    api, admin = credentials
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://fixture"
    ) as client:
        assert (
            await client.get("/inference", headers={"Authorization": f"Bearer {api}"})
        ).status_code == 200
        assert (
            await client.get("/inference", headers={"x-api-key": admin})
        ).status_code == 200
        assert (
            await client.post("/admin", headers={"Authorization": f"Bearer {api}"})
        ).status_code == 401
        assert (
            await client.post("/admin", headers={"x-admin-key": admin})
        ).status_code == 200
        assert (await client.post("/admin")).status_code == 401
        for value in [
            "Bearer",
            "Basic abc",
            "Bearer one two",
            "",
            secrets.token_urlsafe(32),
        ]:
            assert (
                await client.get("/inference", headers={"authorization": value})
            ).status_code == 401
        assert (
            await client.get(
                "/inference",
                headers={"x-api-key": api, "authorization": f"Bearer {admin}"},
            )
        ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["x-api-key", "x-admin-key", "authorization"])
@pytest.mark.parametrize("role", ["api", "admin"])
async def test_carriers_have_consistent_roles_on_actual_routes(
    credentials, carrier, role
):
    token = credentials[0 if role == "api" else 1]
    value = f"Bearer {token}" if carrier == "authorization" else token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://fixture"
    ) as client:
        response = await client.get("/permission", headers={carrier: value})
        assert response.status_code == 200
        assert response.json() == {"permission": role}
        response = await client.post("/admin", headers={carrier: value})
        assert response.status_code == (200 if role == "admin" else 401)


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["x-api-key", "x-admin-key", "authorization"])
@pytest.mark.parametrize("second", ["x-api-key", "x-admin-key", "authorization"])
@pytest.mark.parametrize("second_empty", [False, True])
async def test_ambiguous_headers_rejected_before_handler(
    credentials, first, second, second_empty
):
    api, admin = credentials
    first_value = f"Bearer {api}" if first == "authorization" else api
    second_value = f"Bearer {admin}" if second == "authorization" else admin
    headers = [
        (first, first_value),
        (second.upper(), "" if second_empty else second_value),
    ]
    application = app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://fixture",
    ) as client:
        for method, path in [("GET", "/permission"), ("POST", "/admin")]:
            response = await client.request(method, path, headers=headers)
            assert response.status_code == 401
            assert api not in response.text and admin not in response.text
    assert application.state.permission_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["x-api-key", "x-admin-key", "authorization"])
async def test_duplicate_identical_headers_rejected(credentials, carrier):
    token = credentials[1]
    value = f"Bearer {token}" if carrier == "authorization" else token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://fixture"
    ) as client:
        response = await client.get("/permission", headers=[(carrier, value)] * 2)
        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", [b"Bearer\n", b"Bearer\t", b"Bearer \x7f", b"Bearer \xff"]
)
async def test_nonprintable_authorization_rejected(credentials, bad):
    value = bad + credentials[0].encode("ascii")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://fixture"
    ) as client:
        assert (
            await client.get("/permission", headers=[(b"authorization", value)])
        ).status_code == 401


@pytest.mark.asyncio
async def test_uninitialized_fails_closed_even_with_disable_symbol(monkeypatch):
    monkeypatch.setattr(auth, "DISABLE_AUTH", True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://fixture"
    ) as client:
        assert (await client.get("/inference")).status_code == 503


@pytest.mark.asyncio
async def test_environment_only_no_file_output(tmp_path, monkeypatch):
    import os

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(auth.API_KEY_ENV, secrets.token_urlsafe(32))
    monkeypatch.setenv(auth.ADMIN_KEY_ENV, secrets.token_urlsafe(32))
    await auth.load_auth_keys(False)
    assert auth.API_KEY_ENV not in os.environ and auth.ADMIN_KEY_ENV not in os.environ
    assert not list(tmp_path.iterdir())
    with pytest.raises(RuntimeError):
        await auth.load_auth_keys(False)
    assert auth.AUTH_KEYS is None
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "short",
        "a" * 31,
        "a" * 32 + " ",
        "雪" * 32,
        "a" * 4097,
        "a" * 32 + "\x01",
        "a" * 32 + "\x7f",
        "a" * 32 + "\t",
    ],
)
async def test_invalid_environment_never_echoes_value(invalid, monkeypatch):
    monkeypatch.setenv(auth.API_KEY_ENV, invalid)
    monkeypatch.setenv(auth.ADMIN_KEY_ENV, secrets.token_urlsafe(32))
    with pytest.raises(RuntimeError) as caught:
        await auth.load_auth_keys(False)
    if invalid:
        assert invalid not in str(caught.value)
    assert auth.AUTH_KEYS is None


@pytest.mark.asyncio
async def test_cannot_disable_or_reuse_same_credential(monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv(auth.API_KEY_ENV, token)
    monkeypatch.setenv(auth.ADMIN_KEY_ENV, token)
    with pytest.raises(RuntimeError):
        await auth.load_auth_keys(True)
    with pytest.raises(RuntimeError):
        await auth.load_auth_keys(False)
    assert auth.AUTH_KEYS is None


def request(headers):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin",
            "headers": [
                (key.encode(), value.encode()) for key, value in headers.items()
            ],
        }
    )


@pytest.mark.asyncio
async def test_router_permission_contract(credentials):
    api, admin = credentials
    assert auth.get_key_permission(request({"authorization": f"Bearer {api}"})) == "api"
    assert auth.get_key_permission(request({"x-admin-key": admin})) == "admin"
    with pytest.raises(HTTPException) as ambiguous:
        auth.get_key_permission(request({"x-admin-key": admin, "x-api-key": api}))
    assert ambiguous.value.status_code == 401
    with pytest.raises(HTTPException) as malformed:
        auth.get_key_permission(request({"authorization": "Bearer"}))
    assert malformed.value.status_code == 401
    assert not auth.AUTH_KEYS.verify_key("雪", "api_key")


@pytest.mark.asyncio
async def test_request_log_never_records_headers_query_path_or_body():
    canary = secrets.token_urlsafe(32)
    records = []

    class Recorder:
        def info(self, *args, **kwargs):
            records.append((args, kwargs))

    namespace = {"Request": Request, "xlogger": Recorder()}
    # Execute only the reviewed build-time constant, with no runtime imports.
    exec(compile(ast.parse(SAFE_REQUEST_LOG), "managed_request_log", "exec"), namespace)  # noqa: S102
    fixture = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/{canary}",
            "query_string": f"token={canary}".encode(),
            "headers": [(b"authorization", canary.encode())],
        }
    )
    await namespace["log_request"](fixture)
    assert records and "POST" in str(records)
    assert canary not in str(records)
