"""WebSocket streaming event router for Friday Core."""

import asyncio
import datetime
import json
import logging
import uuid
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from friday.agent.loop import AgentLoop
from friday.sessions.manager import SessionManager

logger = logging.getLogger(__name__)

ws_router = APIRouter()


class SessionConnectionManager:
    """Manages active WebSocket connections and in-flight tasks per session."""

    def __init__(self) -> None:
        self.active_connections: Dict[str, set[WebSocket]] = {}
        self.in_flight_tasks: Dict[str, tuple[asyncio.Task, asyncio.Event]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        logger.info("WebSocket connected for session %s", session_id)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info("WebSocket disconnected for session %s", session_id)

    def cancel_turn(self, session_id: str) -> bool:
        """Signal cancellation to an in-flight turn task."""
        if session_id in self.in_flight_tasks:
            task, cancel_event = self.in_flight_tasks[session_id]
            cancel_event.set()
            task.cancel()
            logger.info("Cancellation signaled for in-flight turn in session %s", session_id)
            return True
        return False


manager = SessionConnectionManager()


@ws_router.websocket("/ws/sessions/{session_id}")
async def websocket_session_endpoint(websocket: WebSocket, session_id: str) -> None:
    session_mgr: SessionManager = websocket.app.state.session_manager
    session = await session_mgr.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    agent_loop: AgentLoop = websocket.app.state.agent_loop
    await manager.connect(session_id, websocket)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "event_id": str(uuid.uuid4()),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "session_id": session_id,
                    "turn_id": "",
                    "type": "error",
                    "payload": {"error": "Invalid JSON message format"},
                })
                continue

            msg_type = data.get("type")

            if msg_type == "turn.cancel":
                manager.cancel_turn(session_id)
                continue

            if msg_type == "turn.submit":
                gaming_mode = getattr(websocket.app.state, "gaming_mode_controller", None)
                if gaming_mode and gaming_mode.active:
                    await websocket.send_json({
                        "event_id": str(uuid.uuid4()),
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "session_id": session_id,
                        "turn_id": "",
                        "type": "error",
                        "payload": {"error": "Gaming Mode is active. Inference turns are blocked."},
                    })
                    continue

                prompt = data.get("prompt", "")
                model_name = data.get("model_name", "default")

                cancel_event = asyncio.Event()

                async def execute_turn():
                    history = await session_mgr.get_history(session_id)
                    final_answer = ""
                    turn_id = ""
                    try:
                        async for event in agent_loop.run_turn(
                            session_id=session_id,
                            user_prompt=prompt,
                            conversation_history=history,
                            model_name=model_name,
                            cancel_event=cancel_event,
                        ):
                            turn_id = event.get("turn_id", turn_id)
                            # Envelope event according to contracts/events.schema.json
                            envelope = {
                                "event_id": str(uuid.uuid4()),
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "type": event["type"],
                                "payload": event.get("payload", {}),
                            }
                            await websocket.send_json(envelope)

                            if event["type"] == "turn.completed":
                                final_answer = event["payload"].get("final_answer", "")

                        # Persist to database
                        await session_mgr.add_message(session_id, role="user", content=prompt)
                        if final_answer:
                            await session_mgr.add_message(session_id, role="assistant", content=final_answer)

                    except asyncio.CancelledError:
                        logger.info("Turn task cancelled cleanly in session %s", session_id)
                        await websocket.send_json({
                            "event_id": str(uuid.uuid4()),
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "type": "error",
                            "payload": {"error": "Turn canceled by user"},
                        })
                    except Exception as exc:
                        logger.error("Error executing turn in session %s: %s", session_id, exc)
                        await websocket.send_json({
                            "event_id": str(uuid.uuid4()),
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "type": "error",
                            "payload": {"error": str(exc)},
                        })
                    finally:
                        manager.in_flight_tasks.pop(session_id, None)

                # Launch turn execution task
                turn_task = asyncio.create_task(execute_turn())
                manager.in_flight_tasks[session_id] = (turn_task, cancel_event)

    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
        manager.cancel_turn(session_id)
    except Exception as exc:
        logger.error("Unhandled WebSocket exception in session %s: %s", session_id, exc)
        manager.disconnect(session_id, websocket)
        manager.cancel_turn(session_id)
