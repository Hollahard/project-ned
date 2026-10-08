import asyncio
from dataclasses import replace

import httpx
import pytest
from conftest import ChunkStream, progress, sse

from hermes_inference import ControlState, StreamLimits, TabbyV3Control
from hermes_inference.errors import (
    AdmissionClosed,
    EffectiveSettingsMismatch,
    IdentityMismatch,
    OperationUncertain,
    ProtocolError,
    RemoteOperationError,
    StaleAdmission,
    UnsupportedManagedRuntime,
)


async def test_load_verifies_effective_settings_and_separate_auth(control, engine, profile):
    status = await control.apply(profile)
    assert status.state == ControlState.READY
    assert status.active_profile == profile
    assert all(engine.auth_valid)
    loads = [payload for _, path, payload in engine.requests if path == "/v1/model/load"]
    assert loads == [profile.payload()]
    assert any(path == "/props" for _, path, _ in engine.requests)


async def test_same_profile_reverified_without_reload(control, engine, profile):
    await control.apply(profile)
    before = len([r for r in engine.requests if r[0] == "POST"])
    await control.apply(profile)
    assert len([r for r in engine.requests if r[0] == "POST"]) == before


async def test_changed_profile_same_model_explicitly_unloads(control, engine, profile):
    await control.apply(profile)
    changed = replace(profile, revision="revision-2", context_length=8192, cache_size=8192)
    await control.apply(changed)
    assert [path for method, path, _ in engine.requests if method == "POST"] == [
        "/v1/model/load",
        "/v1/model/unload",
        "/v1/model/load",
    ]
    assert control.status().active_profile == changed


@pytest.mark.parametrize(
    "body",
    [
        sse({"error": {"message": "synthetic upstream failure"}}),
        sse(progress()) + sse({"error": {"message": "late warmup failure"}}),
        b"event: error\ndata: {}\n\n",
    ],
)
async def test_http_200_error_never_ready(control, engine, profile, body):
    engine.load_body = body
    with pytest.raises(RemoteOperationError):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN
    assert control.status().active_profile is None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"data: {}\n\n",
        b"data: not-json\n\n",
        b"data: []\n\n",
        sse(progress())[:-1],
        sse(progress(status="processing")),
        sse(progress()) + sse(progress("processing", "warmup", 1, 2)),
        sse(progress(module=0, modules=1)),
        sse(progress(module=True)),
        b"data: \xff\n\n",
        sse(progress()) + sse(progress()),
    ],
)
async def test_malformed_or_incomplete_load_fails_closed(control, engine, profile, body):
    engine.load_body = body
    with pytest.raises(ProtocolError):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN


async def test_progress_across_components_and_fragmented_crlf(control, engine, profile):
    body = sse(
        progress("processing", "model", 1, 2),
        progress(module=2, modules=2),
        progress(component="warmup"),
    )
    body = b": keepalive\n\n" + body
    body = body.replace(b"\n", b"\r\n")
    engine.stream_factory = lambda: ChunkStream([bytes([byte]) for byte in body])
    await control.apply(profile)
    assert control.status().state == ControlState.READY


@pytest.mark.parametrize(
    "limits,body",
    [
        (StreamLimits(max_event_bytes=64), b"data: " + b"x" * 65),
        (StreamLimits(max_total_bytes=64), sse(progress())),
        (
            StreamLimits(max_events=1),
            sse(progress("processing", module=1, modules=2), progress(module=2, modules=2)),
        ),
    ],
)
async def test_stream_limits_enforced(engine, credentials, gate, profile, limits, body):
    engine.load_body = body
    control = TabbyV3Control(
        base_url="http://127.0.0.1:5000",
        credentials=credentials,
        gate=gate,
        transport=httpx.MockTransport(engine),
        stream_limits=limits,
    )
    try:
        with pytest.raises(ProtocolError):
            await control.apply(profile)
        assert control.status().state == ControlState.UNCERTAIN
    finally:
        await control.aclose()


async def test_wrong_absolute_path_not_just_same_basename(control, engine, profile):
    engine.props_override["model_path"] = r"G:\other\model-a"
    with pytest.raises(IdentityMismatch):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_seq_len", 2048),
        ("cache_size", 8192),
        ("cache_mode", "FP16"),
        ("max_batch_size", 2),
        ("chunk_size", 1024),
        ("use_vision", True),
        ("draft", {"id": "unverified"}),
        ("hermes_native_draft_enabled", True),
    ],
)
async def test_effective_settings_must_match(control, engine, profile, field, value):
    engine.parameters_override[field] = value
    with pytest.raises(EffectiveSettingsMismatch):
        await control.apply(profile)


@pytest.mark.parametrize("reported", [None, 0, "false"])
async def test_managed_draft_probe_requires_boolean_false(control, engine, profile, reported):
    engine.parameters_override["hermes_native_draft_enabled"] = reported
    with pytest.raises(UnsupportedManagedRuntime):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN
    assert control.status().active_profile is None


async def test_stock_card_without_managed_draft_probe_is_unsupported(control, engine, profile):
    original = engine.card

    def stock_card():
        card = original()
        del card["parameters"]["hermes_native_draft_enabled"]
        return card

    engine.card = stock_card
    with pytest.raises(UnsupportedManagedRuntime):
        await control.apply(profile)
    assert control.status().active_profile is None


async def test_observed_draft_load_phase_is_rejected_before_ready(control, engine, profile):
    engine.load_body = sse(progress(component="draft"), progress())
    with pytest.raises(EffectiveSettingsMismatch, match="draft component"):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN


async def test_resolved_path_identity_accepts_catalog_alias(control, engine, profile):
    alias = replace(profile, model_name="catalog-alias")
    engine.props_override["model_path"] = r"G:\models\Model-A"
    engine.card_id_override = "Model-A"
    await control.apply(alias)
    assert control.status().active_profile == alias


async def test_same_basename_at_another_resolved_path_is_still_rejected(control, engine, profile):
    alias = replace(profile, model_name="catalog-alias")
    engine.props_override["model_path"] = r"G:\other\model-a"
    engine.card_id_override = "model-a"
    with pytest.raises(IdentityMismatch):
        await control.apply(alias)


async def test_props_must_agree_with_model_card(control, engine, profile):
    engine.props_override["default_generation_settings"] = {"n_ctx": 2048}
    with pytest.raises(EffectiveSettingsMismatch):
        await control.apply(profile)


@pytest.mark.parametrize("reported", ["q6", " 6,6 ", " Q6 "])
async def test_raw_cache_mode_cannot_hide_upstream_fp16_fallback(
    control, engine, profile, reported
):
    engine.parameters_override["cache_mode"] = reported
    with pytest.raises(ProtocolError, match="cache precision"):
        await control.apply(profile)
    assert control.status().active_profile is None


async def test_exact_upstream_cache_alias_remains_supported(control, engine, profile):
    engine.parameters_override["cache_mode"] = "Q6"
    assert (await control.apply(profile)).state == ControlState.READY


async def test_wrong_request_profile_cannot_generate(control, engine, profile, second_profile):
    await control.apply(profile)
    before = len(engine.requests)
    with pytest.raises(IdentityMismatch):
        async with control.generation(second_profile):
            pytest.fail("wrong model was admitted")
    assert len(engine.requests) == before


async def test_generation_reverifies_actual_model_and_expires_lease(control, engine, profile):
    await control.apply(profile)
    async with control.generation(profile) as lease:
        lease.ensure_valid()
    with pytest.raises(OperationUncertain):
        lease.ensure_valid()
    engine.card_id_override = "external-swap"
    with pytest.raises(IdentityMismatch):
        async with control.generation(profile):
            pytest.fail("unverified model admitted")


async def test_transition_waits_for_entire_generation(control, engine, profile, second_profile):
    await control.apply(profile)
    started, release = asyncio.Event(), asyncio.Event()

    async def generate():
        async with control.generation(profile):
            started.set()
            await release.wait()

    generation = asyncio.create_task(generate())
    await started.wait()
    transition = asyncio.create_task(control.apply(second_profile))
    await asyncio.sleep(0)
    assert not transition.done()
    assert not any(path == "/v1/model/unload" for _, path, _ in engine.requests)
    release.set()
    await generation
    await transition
    assert control.status().active_profile == second_profile


async def test_closed_admission_blocks_all_new_loads_and_generations(
    control, engine, gate, profile
):
    gate.close()
    with pytest.raises(AdmissionClosed):
        await control.apply(profile)
    with pytest.raises(AdmissionClosed):
        async with control.generation(profile):
            pytest.fail("closed gate admitted generation")
    assert engine.requests == []


async def test_gate_closes_during_load_prevents_ready_commit(control, engine, gate, profile):
    started, release = asyncio.Event(), asyncio.Event()
    engine.stream_factory = lambda: ChunkStream([sse(progress())], started=started, release=release)
    task = asyncio.create_task(control.apply(profile))
    await started.wait()
    gate.close()
    release.set()
    with pytest.raises(AdmissionClosed):
        await task
    assert control.status().state == ControlState.UNCERTAIN


async def test_gate_close_reopen_during_load_is_fenced(control, engine, gate, profile):
    started, release = asyncio.Event(), asyncio.Event()
    engine.stream_factory = lambda: ChunkStream([sse(progress())], started=started, release=release)
    task = asyncio.create_task(control.apply(profile))
    await started.wait()
    closed = gate.close()
    gate.open(expected_generation=closed.generation)
    release.set()
    with pytest.raises(StaleAdmission):
        await task


async def test_cancellation_preserves_uncertainty_no_automatic_retry(control, engine, profile):
    started, release = asyncio.Event(), asyncio.Event()
    stream = ChunkStream([sse(progress())], started=started, release=release)
    engine.stream_factory = lambda: stream
    task = asyncio.create_task(control.apply(profile))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    assert control.status().state == ControlState.UNCERTAIN
    count = len(engine.requests)
    with pytest.raises(OperationUncertain):
        await control.apply(profile)
    with pytest.raises(OperationUncertain):
        await control.unload()
    assert len(engine.requests) == count
    # Fixture now represents independent evidence that the owned load completed.
    await control.reconcile(profile)
    assert control.status().state == ControlState.READY


async def test_absent_model_cannot_resolve_detached_load(control, engine, profile):
    engine.load_body = b""
    engine.load_applies = False
    with pytest.raises(ProtocolError):
        await control.apply(profile)
    with pytest.raises(IdentityMismatch):
        await control.reconcile(profile)
    assert control.status().state == ControlState.UNCERTAIN


async def test_transport_disconnect_fails_closed(control, engine, profile):
    engine.stream_factory = lambda: ChunkStream(
        [], error=httpx.ReadError("synthetic disconnected stream")
    )
    with pytest.raises(OperationUncertain):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN


async def test_overall_load_deadline(engine, credentials, gate, profile):
    engine.stream_factory = lambda: ChunkStream([], release=asyncio.Event())
    control = TabbyV3Control(
        base_url="http://127.0.0.1:5000",
        credentials=credentials,
        gate=gate,
        transport=httpx.MockTransport(engine),
        operation_timeout=0.01,
    )
    try:
        with pytest.raises(OperationUncertain):
            await control.apply(profile)
        assert control.status().state == ControlState.UNCERTAIN
    finally:
        await control.aclose()


async def test_unload_allowed_with_closed_gate_but_verifies_absence(control, engine, gate, profile):
    await control.apply(profile)
    gate.close()
    await control.unload()
    assert control.status().state == ControlState.UNLOADED
    assert control.status().active_profile is None


async def test_failed_unload_is_not_reported_as_released(control, engine, profile):
    await control.apply(profile)
    engine.unload_applies = False
    with pytest.raises(IdentityMismatch):
        await control.unload()
    assert control.status().state == ControlState.UNCERTAIN


async def test_remote_errors_do_not_echo_sensitive_body(
    control, engine, profile, credentials, caplog
):
    engine.load_body = sse({"error": {"message": credentials.admin_key}})
    with pytest.raises(RemoteOperationError) as caught:
        await control.apply(profile)
    assert credentials.admin_key not in str(caught.value)
    assert credentials.admin_key not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:5000",
        "http://127.0.0.1:5000/path",
        "http://user:pass@127.0.0.1:5000",
        "http://127.0.0.1:5000?token=x",
    ],
)
def test_only_loopback_origins_without_credentials(credentials, gate, url):
    with pytest.raises(ValueError):
        TabbyV3Control(base_url=url, credentials=credentials, gate=gate)


@pytest.mark.parametrize("status", [400, 401, 500, 503])
async def test_non_200_load_cannot_commit(control, engine, profile, status):
    engine.load_status = status
    with pytest.raises(RemoteOperationError):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN


async def test_wrong_load_content_type(control, engine, profile):
    engine.load_content_type = "application/json"
    with pytest.raises(ProtocolError):
        await control.apply(profile)


async def test_reconcile_cannot_adopt_unrelated_profile(control, profile, second_profile):
    await control.apply(profile)
    with pytest.raises(IdentityMismatch):
        await control.reconcile(second_profile)


async def test_queued_transition_is_rejected_after_gate_changes(
    control, engine, gate, profile, second_profile
):
    await control.apply(profile)
    release, started = asyncio.Event(), asyncio.Event()

    async def generate():
        async with control.generation(profile):
            started.set()
            await release.wait()

    active = asyncio.create_task(generate())
    await started.wait()
    queued = asyncio.create_task(control.apply(second_profile))
    await asyncio.sleep(0)
    gate.close()
    release.set()
    with pytest.raises(AdmissionClosed):
        await active
    with pytest.raises(AdmissionClosed):
        await queued
    assert sum(path == "/v1/model/load" for _, path, _ in engine.requests) == 1


async def test_generation_cancellation_invalidates_lease(control, profile):
    await control.apply(profile)
    started = asyncio.Event()
    leases = []

    async def generate():
        async with control.generation(profile) as lease:
            leases.append(lease)
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(generate())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert control.status().state == ControlState.UNCERTAIN
    with pytest.raises(OperationUncertain):
        leases[0].ensure_valid()


async def test_failed_generation_body_invalidates_readiness(control, profile):
    await control.apply(profile)
    with pytest.raises(RuntimeError, match="synthetic generation failure"):
        async with control.generation(profile):
            raise RuntimeError("synthetic generation failure")
    assert control.status().state == ControlState.UNCERTAIN


async def test_non_no_model_503_is_not_treated_as_unloaded(engine, credentials, gate, profile):
    async def handler(request):
        return httpx.Response(503, json={"detail": "engine busy"})

    control = TabbyV3Control(
        base_url="http://127.0.0.1:5000",
        credentials=credentials,
        gate=gate,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RemoteOperationError):
            await control.apply(profile)
        assert control.status().state == ControlState.UNCERTAIN
    finally:
        await control.aclose()


async def test_bounded_observation_response(credentials, gate, profile):
    async def handler(request):
        return httpx.Response(200, content=b"x" * 129)

    control = TabbyV3Control(
        base_url="http://127.0.0.1:5000",
        credentials=credentials,
        gate=gate,
        transport=httpx.MockTransport(handler),
        max_json_bytes=128,
    )
    try:
        with pytest.raises(ProtocolError, match="byte limit"):
            await control.apply(profile)
    finally:
        await control.aclose()


async def test_identity_change_between_observations_is_rejected(control, engine, profile):
    await control.apply(profile)
    observations = 0

    async def change_between_cards(request):
        nonlocal observations
        if request.url.path == "/v1/model":
            observations += 1
            if observations == 2:
                engine.card_id_override = "external-model"

    engine.on_request = change_between_cards
    with pytest.raises(IdentityMismatch, match="changed during observation"):
        async with control.generation(profile):
            pytest.fail("inconsistent observation was admitted")


async def test_gate_closed_at_last_observation_prevents_commit(control, engine, gate, profile):
    seen = 0

    async def close_at_final_card(request):
        nonlocal seen
        if request.url.path == "/v1/model":
            seen += 1
            if seen == 3:
                gate.close()

    engine.on_request = close_at_final_card
    with pytest.raises(AdmissionClosed):
        await control.apply(profile)
    assert control.status().state == ControlState.UNCERTAIN
