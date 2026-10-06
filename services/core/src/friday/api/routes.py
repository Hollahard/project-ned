"""REST routes for Friday Core."""

import json
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from friday.sessions.manager import Session
from friday.inference.protocol import ModelProfile

router = APIRouter(prefix="/api/v1")


class CreateSessionPayload(BaseModel):
    title: str = "New Session"
    working_directory: str = "."
    model_profile: str = "default"


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
async def create_session(request: Request, payload: CreateSessionPayload) -> Session:
    mgr = request.app.state.session_manager
    return await mgr.create_session(
        title=payload.title,
        working_directory=payload.working_directory,
        model_profile=payload.model_profile,
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
