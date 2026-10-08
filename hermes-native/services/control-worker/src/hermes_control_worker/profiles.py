"""Reuse the existing inference schema; persist only validated settings."""

import dataclasses
import json
import re
import sqlite3
from pathlib import Path
from typing import get_type_hints

from hermes_inference.errors import ProfileValidationError
from hermes_inference.profiles import LoadProfile

from .errors import INVALID_PARAMS, INVALID_PROFILE, STATE_INVALID, ControlError

MAX_PROFILES = 128
MAX_PROFILE_BYTES = 16_384
MAX_TEXT_BYTES = 4096
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)


def exact_params(value: object, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ControlError(*INVALID_PARAMS)
    return value


def bounded_text(value: object, *, limit: int = MAX_TEXT_BYTES) -> bool:
    if type(value) is not str or not value.strip() or any(ord(c) < 32 for c in value):
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def validate_profile(value: object) -> dict:
    if type(value) is not dict:
        raise ControlError(*INVALID_PROFILE)
    for item in value.values():
        if isinstance(item, str) and not bounded_text(item):
            raise ControlError(*INVALID_PROFILE)
    try:
        profile = LoadProfile.from_mapping(value)
        normalized = dataclasses.asdict(profile)
        if len(json.dumps(normalized).encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ControlError(*INVALID_PROFILE)
    except (ProfileValidationError, TypeError, ValueError, UnicodeError):
        raise ControlError(*INVALID_PROFILE) from None
    return normalized


def profile_schema() -> dict:
    hints = get_type_hints(LoadProfile)
    fields = []
    for item in dataclasses.fields(LoadProfile):
        descriptor = {
            "name": item.name,
            "type": hints[item.name].__name__,
            "required": item.default is dataclasses.MISSING,
        }
        if item.default is not dataclasses.MISSING:
            descriptor["default"] = item.default
        fields.append(descriptor)
    return {
        "schema_source": "hermes_inference.LoadProfile",
        "fields": fields,
        "validation_scope": "schema",
        "artifact_verification": False,
        "limits": {
            "max_profiles": MAX_PROFILES,
            "profile_bytes": MAX_PROFILE_BYTES,
            "text_bytes": MAX_TEXT_BYTES,
        },
    }


def _identifier(value: object) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ControlError(*INVALID_PARAMS)
    return value


def _revision(value: object, *, allow_none: bool) -> int | None:
    if value is None and allow_none:
        return None
    if type(value) is not int or not 1 <= value < 2**63 - 1:
        raise ControlError(*INVALID_PARAMS)
    return value


class ProfileStore:
    """One process holds the state lock; SQL still fences optimistic revisions."""

    def __init__(self, state: Path):
        self._db = sqlite3.connect(state / "profiles.sqlite3", timeout=1.0)
        try:
            self._db.execute("PRAGMA trusted_schema=OFF")
            self._db.execute("PRAGMA journal_mode=DELETE")
            self._db.execute("PRAGMA synchronous=FULL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ControlError(*STATE_INVALID)
            if version == 0:
                if self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ControlError(*STATE_INVALID)
                with self._db:
                    # sqlite3's legacy transaction mode does not begin a transaction
                    # for DDL. Fence tables, seed data and version as one unit so an
                    # interrupted first launch remains a recoverable empty database.
                    self._db.execute("BEGIN IMMEDIATE")
                    self._db.execute(
                        "CREATE TABLE profiles (profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                        "revision INTEGER NOT NULL CHECK(revision > 0), payload TEXT NOT NULL)"
                    )
                    self._db.execute(
                        "CREATE TABLE profile_clock (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                        "revision INTEGER NOT NULL CHECK(revision>=0))"
                    )
                    self._db.execute("INSERT INTO profile_clock VALUES(1,0)")
                    self._db.execute("PRAGMA user_version=1")
            self._db.execute("SELECT profile_id, name, revision, payload FROM profiles LIMIT 0")
            self._db.execute("SELECT revision FROM profile_clock WHERE singleton=1")
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def list_profiles(self) -> dict:
        # Summaries keep the entire response bounded even when profiles have long paths.
        rows = self._db.execute(
            "SELECT profile_id,name,revision FROM profiles ORDER BY profile_id LIMIT ?",
            (MAX_PROFILES + 1,),
        ).fetchall()
        if len(rows) > MAX_PROFILES:
            raise ControlError(*STATE_INVALID)
        return {"profiles": [self._summary(row) for row in rows]}

    @staticmethod
    def _summary(row) -> dict:
        profile_id, name, revision = row
        if (
            _identifier(profile_id) != profile_id
            or not bounded_text(name, limit=128)
            or _revision(revision, allow_none=False) != revision
        ):
            raise ControlError(*STATE_INVALID)
        return {"profile_id": profile_id, "name": name, "revision": revision}

    def get(self, params: object) -> dict:
        values = exact_params(params, {"profile_id"})
        profile_id = _identifier(values["profile_id"])
        row = self._db.execute(
            "SELECT profile_id,name,revision,payload FROM profiles WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        if row is None:
            raise ControlError("PROFILE_NOT_FOUND", "The saved profile does not exist.")
        result = self._summary(row[:3])
        if type(row[3]) is not str or len(row[3].encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ControlError(*STATE_INVALID)
        result["profile"] = validate_profile(json.loads(row[3]))
        result["validation_scope"] = "schema"
        return result

    def save(self, params: object) -> dict:
        values = exact_params(params, {"profile_id", "name", "expected_revision", "profile"})
        profile_id = _identifier(values["profile_id"])
        if not bounded_text(values["name"], limit=128):
            raise ControlError(*INVALID_PARAMS)
        expected = _revision(values["expected_revision"], allow_none=True)
        profile = validate_profile(values["profile"])
        payload = json.dumps(profile, separators=(",", ":"), ensure_ascii=False)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            current = self._db.execute(
                "SELECT revision FROM profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
            if (current[0] if current else None) != expected:
                raise ControlError("REVISION_CONFLICT", "The saved profile changed; read it again.")
            if current is None:
                count = self._db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
                if count >= MAX_PROFILES:
                    raise ControlError("PROFILE_LIMIT", "The saved profile limit has been reached.")
            clock = self._db.execute(
                "SELECT revision FROM profile_clock WHERE singleton=1"
            ).fetchone()
            if clock is None or type(clock[0]) is not int or not 0 <= clock[0] < 2**63 - 2:
                raise ControlError(*STATE_INVALID)
            # A deleted/recreated slug must not accept an old incarnation's revision.
            revision = clock[0] + 1
            self._db.execute("UPDATE profile_clock SET revision=? WHERE singleton=1", (revision,))
            self._db.execute(
                "INSERT INTO profiles VALUES(?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET "
                "name=excluded.name,revision=excluded.revision,payload=excluded.payload",
                (profile_id, values["name"], revision, payload),
            )
        return {"profile_id": profile_id, "revision": revision, "validation_scope": "schema"}

    def delete(self, params: object) -> dict:
        values = exact_params(params, {"profile_id", "expected_revision"})
        profile_id = _identifier(values["profile_id"])
        revision = _revision(values["expected_revision"], allow_none=False)
        with self._db:
            deleted = self._db.execute(
                "DELETE FROM profiles WHERE profile_id=? AND revision=?", (profile_id, revision)
            ).rowcount
            if not deleted:
                raise ControlError("REVISION_CONFLICT", "The saved profile changed; read it again.")
        return {"deleted": True, "profile_id": profile_id}
