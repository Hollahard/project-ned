"""REST routes for Friday Core."""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel

from friday.sessions.manager import Session
from friday.inference.protocol import ModelProfile
from friday.inference.telemetry import GpuTelemetry
from friday.inference.preflight import PreflightResult, check_vram_preflight
from friday.inference.gaming_mode import GamingModeStatus

router = APIRouter(prefix="/api/v1")

DEFAULT_PRIMARY_MODEL = "Mistral-Small-3.1-24B-Instruct-2503-exl3"


class CreateSessionPayload(BaseModel):
    model_config = {"extra": "ignore"}

    title: Optional[str] = "New Session"
    working_directory: Optional[str] = "."
    model_profile: Optional[str] = None
    model: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TurnPayload(BaseModel):
    prompt: str
    model_name: str = "default"


class MintApprovalPayload(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]


@router.get("/sessions", response_model=List[Session])
async def list_sessions(request: Request) -> List[Session]:
    mgr = request.app.state.session_manager
    return await mgr.list_sessions()


@router.post("/sessions", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    payload: Optional[CreateSessionPayload] = Body(default=None),
) -> Session:
    mgr = request.app.state.session_manager
    p = payload or CreateSessionPayload()
    title = p.title if (p.title is not None and p.title != "") else "New Session"
    working_directory = (
        p.working_directory
        if (p.working_directory is not None and p.working_directory != "")
        else "."
    )
    model_profile = p.model or p.model_profile or DEFAULT_PRIMARY_MODEL
    return await mgr.create_session(
        title=title,
        working_directory=working_directory,
        model_profile=model_profile,
    )


@router.get("/sessions/{session_id}", response_model=Session)
async def get_session(request: Request, session_id: str) -> Session:
    mgr = request.app.state.session_manager
    session = await mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> None:
    mgr = request.app.state.session_manager
    await mgr.delete_session(session_id)


@router.post("/sessions/{session_id}/turns")
async def run_turn(request: Request, session_id: str, payload: TurnPayload) -> dict:
    if getattr(request.app.state, "gaming_mode_controller", None) and request.app.state.gaming_mode_controller.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gaming Mode is active. Inference turns are blocked.",
        )

    session_mgr = request.app.state.session_manager
    session = await session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    history = await session_mgr.get_history(session_id)
    loop = request.app.state.agent_loop

    events = []
    final_answer = ""
    async for event in loop.run_turn(
        session_id=session_id,
        user_prompt=payload.prompt,
        conversation_history=history,
        model_name=payload.model_name,
    ):
        events.append(event)
        if event["type"] == "turn.completed":
            final_answer = event["payload"].get("final_answer", "")

    # Save to history
    await session_mgr.add_message(session_id, role="user", content=payload.prompt)
    if final_answer:
        await session_mgr.add_message(session_id, role="assistant", content=final_answer)

    return {
        "session_id": session_id,
        "final_answer": final_answer,
        "event_count": len(events),
        "events": events,
    }


@router.post("/approvals/mint")
async def mint_approval_token(request: Request, payload: MintApprovalPayload) -> dict:
    """Internal endpoint used by the Rust supervisor upon native OS user approval."""
    token_mgr = request.app.state.token_manager
    token, args_hash = token_mgr.mint_token(payload.tool_name, payload.arguments)
    return {
        "one_shot_token": token,
        "args_hash": args_hash,
        "tool_name": payload.tool_name,
    }


class LoadModelPayload(BaseModel):
    name: str
    model_dir: str = ""
    context_length: int = 32768
    kv_cache_dtype: str = "q6"


class PreflightPayload(BaseModel):
    model_name: str
    context_length: int = 32768
    kv_cache_dtype: str = "q6"
    available_vram_mb: float | None = None
    bpw: float | None = None


@router.get("/models")
async def list_models(request: Request) -> list:
    backend = request.app.state.inference_backend
    models = await backend.list_models()
    return [m.model_dump() for m in models]


@router.post("/models/load")
async def load_model(request: Request, payload: LoadModelPayload) -> dict:
    if getattr(request.app.state, "gaming_mode_controller", None) and request.app.state.gaming_mode_controller.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gaming Mode is active. Model loading is blocked until Gaming Mode is deactivated.",
        )

    backend = request.app.state.inference_backend
    profile = ModelProfile(
        name=payload.name,
        model_dir=payload.model_dir,
        context_length=payload.context_length,
        kv_cache_dtype=payload.kv_cache_dtype,
    )
    try:
        await backend.load_model(profile)
        return {"status": "ok", "loaded_model": payload.name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/models/unload")
async def unload_model(request: Request) -> dict:
    backend = request.app.state.inference_backend
    try:
        await backend.unload_model()
        return {"status": "ok", "message": "Model unloaded"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/models/preflight", response_model=PreflightResult)
async def model_preflight(request: Request, payload: PreflightPayload) -> PreflightResult:
    available_vram = payload.available_vram_mb
    if available_vram is None:
        telem_provider = getattr(request.app.state, "telemetry_provider", None)
        if telem_provider:
            telem = telem_provider.get_gpu_telemetry()
            available_vram = telem.vram_total_mb if telem.available else 32000.0
        else:
            available_vram = 32000.0

    return check_vram_preflight(
        model_name=payload.model_name,
        context_length=payload.context_length,
        kv_cache_dtype=payload.kv_cache_dtype,
        available_vram_mb=available_vram,
        bpw=payload.bpw,
    )


@router.get("/telemetry/gpu", response_model=GpuTelemetry)
async def get_gpu_telemetry(request: Request) -> GpuTelemetry:
    telem_provider = getattr(request.app.state, "telemetry_provider", None)
    if not telem_provider:
        return GpuTelemetry(available=False, device_name="Telemetry provider not initialized")
    return telem_provider.get_gpu_telemetry()


@router.post("/gaming-mode/activate", response_model=GamingModeStatus)
async def activate_gaming_mode(request: Request) -> GamingModeStatus:
    gaming_mode = getattr(request.app.state, "gaming_mode_controller", None)
    if not gaming_mode:
        raise HTTPException(status_code=500, detail="Gaming mode controller not initialized")
    backend = request.app.state.inference_backend
    agent_loop = getattr(request.app.state, "agent_loop", None)
    return await gaming_mode.activate(backend=backend, agent_loop=agent_loop)


@router.post("/gaming-mode/deactivate", response_model=GamingModeStatus)
async def deactivate_gaming_mode(request: Request) -> GamingModeStatus:
    gaming_mode = getattr(request.app.state, "gaming_mode_controller", None)
    if not gaming_mode:
        raise HTTPException(status_code=500, detail="Gaming mode controller not initialized")
    return await gaming_mode.deactivate()


@router.get("/gaming-mode/status", response_model=GamingModeStatus)
async def get_gaming_mode_status(request: Request) -> GamingModeStatus:
    gaming_mode = getattr(request.app.state, "gaming_mode_controller", None)
    if not gaming_mode:
        return GamingModeStatus(active=False, message="Gaming mode not initialized")
    return gaming_mode.get_status()


@router.get("/runtime/status")
async def runtime_status(request: Request) -> dict:
    backend = request.app.state.inference_backend
    health = await backend.health()
    telem_provider = getattr(request.app.state, "telemetry_provider", None)
    telemetry = telem_provider.get_gpu_telemetry() if telem_provider else GpuTelemetry()
    gaming_mode = getattr(request.app.state, "gaming_mode_controller", None)
    gm_status = gaming_mode.get_status() if gaming_mode else GamingModeStatus(active=False, message="Not initialized")

    return {
        "status": "online",
        "inference": health.model_dump(),
        "telemetry": telemetry.model_dump(),
        "gaming_mode": gm_status.model_dump(),
    }
