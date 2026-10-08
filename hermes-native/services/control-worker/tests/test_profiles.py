import dataclasses
import sqlite3

import pytest
from hermes_inference import LoadProfile

from hermes_control_worker.errors import ControlError
from hermes_control_worker.profiles import (
    MAX_PROFILES,
    ProfileStore,
    profile_schema,
    validate_profile,
)


def save(profile, *, slug="small", revision=None, name="Small"):
    return {"profile_id": slug, "name": name, "expected_revision": revision, "profile": profile}


def test_schema_is_derived_from_existing_model(profile):
    schema = profile_schema()
    assert [field["name"] for field in schema["fields"]] == [
        field.name for field in dataclasses.fields(LoadProfile)
    ]
    assert validate_profile(profile) == dataclasses.asdict(LoadProfile.from_mapping(profile))
    assert schema["artifact_verification"] is False


@pytest.mark.parametrize(
    "patch",
    [
        {"api_key": "must-not-persist"},
        {"context_length": True},
        {"cache_size": 257},
        {"chunk_size": 255},
        {"model_name": "../elsewhere"},
        {"expected_model_path": "relative/model"},
        {"artifact_id": "x" * 4097},
        {"artifact_id": "\ud800"},
    ],
)
def test_invalid_profile_has_fixed_error(profile, patch):
    with pytest.raises(ControlError) as error:
        validate_profile(profile | patch)
    assert error.value.code == "INVALID_PROFILE"
    assert "must-not-persist" not in str(error.value)


def test_profile_durability_and_optimistic_revision(tmp_path, profile):
    store = ProfileStore(tmp_path)
    created = store.save(save(profile))
    assert created["revision"] == 1
    with pytest.raises(ControlError, match="changed"):
        store.save(save(profile, revision=None))
    with pytest.raises(ControlError):
        store.save(save(profile | {"cache_size": 1}, revision=1))
    assert store.get({"profile_id": "small"})["revision"] == 1
    updated = store.save(save(profile | {"cache_mode": "Q8"}, revision=1))
    assert updated["revision"] == 2
    store.close()
    store = ProfileStore(tmp_path)
    assert store.get({"profile_id": "small"})["profile"]["cache_mode"] == "8,8"
    assert store.list_profiles()["profiles"] == [
        {"profile_id": "small", "name": "Small", "revision": 2}
    ]
    with pytest.raises(ControlError):
        store.delete({"profile_id": "small", "expected_revision": 1})
    assert store.delete({"profile_id": "small", "expected_revision": 2})["deleted"] is True
    recreated = store.save(save(profile))
    assert recreated["revision"] == 3
    with pytest.raises(ControlError):
        store.save(save(profile, revision=1))
    store.close()


@pytest.mark.parametrize(
    "failure_statement",
    ["CREATE TABLE profiles", "CREATE TABLE profile_clock", "PRAGMA user_version=1"],
)
def test_interrupted_initialization_rolls_back_and_reopens(
    tmp_path, profile, monkeypatch, failure_statement
):
    connect = sqlite3.connect

    class InterruptedCreation(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            result = super().execute(statement, *args, **kwargs)
            if statement.startswith(failure_statement):
                raise sqlite3.OperationalError("Injected initialization interruption")
            return result

    with monkeypatch.context() as patch:
        patch.setattr(
            sqlite3,
            "connect",
            lambda *args, **kwargs: connect(*args, factory=InterruptedCreation, **kwargs),
        )
        with pytest.raises(sqlite3.OperationalError, match="Injected initialization"):
            ProfileStore(tmp_path)

    db = connect(tmp_path / "profiles.sqlite3")
    try:
        assert db.execute("PRAGMA user_version").fetchone() == (0,)
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        db.close()
    reopened = ProfileStore(tmp_path)
    try:
        assert reopened.save(save(profile))["revision"] == 1
        assert reopened.get({"profile_id": "small"})["profile"] == validate_profile(profile)
    finally:
        reopened.close()


def test_store_limits_and_strict_params(tmp_path, profile):
    store = ProfileStore(tmp_path)
    with pytest.raises(ControlError):
        store.save(save(profile) | {"path": "other.sqlite"})
    with pytest.raises(ControlError):
        store.save(save(profile, slug="../../bad"))
    with pytest.raises(ControlError):
        store.save(save(profile, name="é" * 65))
    for number in range(MAX_PROFILES):
        store.save(save(profile, slug=f"p{number}"))
    with pytest.raises(ControlError) as error:
        store.save(save(profile, slug="one-more"))
    assert error.value.code == "PROFILE_LIMIT"
    assert len(store.list_profiles()["profiles"]) == MAX_PROFILES
    store.close()
