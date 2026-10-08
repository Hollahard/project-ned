from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from hermes_inference import Credentials, InMemoryAdmissionGate, LoadProfile, normalize_cache_mode
from hermes_inference.admission import require_admission
from hermes_inference.errors import AdmissionClosed, ProfileValidationError, StaleAdmission
from hermes_inference.profiles import canonical_model_path


@pytest.mark.parametrize(
    "given,expected",
    [("q4", "4,4"), ("Q6", "6,6"), (" q8 ", "8,8"), ("fp16", "FP16"), ("2, 8", "2,8")],
)
def test_cache_aliases_are_canonical(given, expected):
    assert normalize_cache_mode(given) == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"cache_mode": "q5"},
        {"cache_mode": "9,4"},
        {"cache_size": 4000},
        {"context_length": 8192},
        {"max_batch_size": True},
        {"chunk_size": 0},
        {"chunk_size": 1},
        {"chunk_size": 255},
        {"chunk_size": 257},
        {"chunk_size": 2049},
        {"vision": "true"},
        {"revision": ""},
        {"artifact_id": 5},
        {"model_name": "../model"},
        {"model_name": r"C:\model"},
        {"expected_model_path": "relative/model"},
        {"expected_model_path": r"G:\models\..\model"},
    ],
)
def test_invalid_profiles_fail_before_io(profile, changes):
    with pytest.raises(ProfileValidationError):
        replace(profile, **changes)


def test_immutable_profile_and_explicit_payload(profile):
    with pytest.raises(FrozenInstanceError):
        profile.context_length = 8192
    assert profile.payload()["cache_mode"] == "6,6"
    assert profile.payload()["backend"] == "exllamav3"
    assert profile.payload()["draft_model"] == {"draft_mode": "disabled"}
    assert "artifact_id" not in profile.payload()


def test_unknown_fields_rejected(profile):
    with pytest.raises(ProfileValidationError, match="unsupported"):
        LoadProfile.from_mapping({**asdict(profile), "bpw": 4.0})
    with pytest.raises(ProfileValidationError, match="missing"):
        LoadProfile.from_mapping({})


def test_absolute_path_comparison_is_windows_aware():
    assert canonical_model_path("G:/Models/Model-A") == canonical_model_path(r"g:\models\model-a")
    assert canonical_model_path("/models/Model-A") != canonical_model_path("/models/model-a")


def test_credentials_are_environment_only_and_redacted(credentials):
    result = Credentials.from_environment(
        {
            "HERMES_TABBY_API_KEY": credentials.inference_key,
            "HERMES_TABBY_ADMIN_KEY": credentials.admin_key,
        }
    )
    assert result == credentials
    assert credentials.inference_key not in repr(result)
    assert credentials.admin_key not in repr(result)
    with pytest.raises(ValueError):
        Credentials.from_environment({})


def test_gate_starts_closed_and_fences_reopen():
    gate = InMemoryAdmissionGate()
    with pytest.raises(AdmissionClosed):
        require_admission(gate)
    first = gate.open(expected_generation=0)
    gate.close()
    with pytest.raises(StaleAdmission):
        gate.open(expected_generation=first.generation)
    gate.open(expected_generation=gate.snapshot().generation)
    with pytest.raises(StaleAdmission):
        require_admission(gate, first)
