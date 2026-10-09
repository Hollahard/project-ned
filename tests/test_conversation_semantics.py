"""Real conversation semantics test suite.

Verifies deterministic session flow (session.create, prompt.submit via AIAgent /
synthetic provider), delta streaming, UI state transitions, transport ambiguity
fencing (uncertain-submit defense), session interruption / cancellation, and
profile-scoped conversation history fencing.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
import pytest


# ==============================================================================
# Deterministic Synthetic Provider & AIAgent Mock Engine
# ==============================================================================


class SyntheticProviderError(RuntimeError):
    """Raw synthetic provider error surfaced verbatim."""
    pass


class DeterministicSyntheticProvider:
    """Deterministic LLM provider mock requiring zero external API keys or network."""

    def __init__(self) -> None:
        self.canned_responses: Dict[str, List[str]] = {
            "hello": ["Hello", " there", ", human!"],
            "compute": ["Thinking...", " Result is 42."],
            "needs_tool": ["CALL_TOOL:list_files", "Final answer after files."],
        }
        self.should_fail: bool = False
        self.failure_message: str = "Synthetic upstream provider error 503"
        self.interrupted: bool = False

    async def stream_completion(
        self, prompt: str, interrupt_event: Optional[asyncio.Event] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if self.should_fail:
            raise SyntheticProviderError(self.failure_message)

        chunks = self.canned_responses.get(
            prompt.lower().strip(), ["Echo: ", prompt]
        )

        for idx, chunk in enumerate(chunks):
            if interrupt_event and interrupt_event.is_set():
                self.interrupted = True
                yield {"type": "interrupted", "chunk_index": idx}
                return

            if chunk.startswith("CALL_TOOL:"):
                tool_name = chunk.split(":", 1)[1]
                yield {
                    "type": "tool_call",
                    "id": f"call-{idx}",
                    "name": tool_name,
                    "arguments": '{"path": "."}',
                }
            else:
                yield {
                    "type": "text_delta",
                    "chunk_index": idx,
                    "text": chunk,
                }
            await asyncio.sleep(0.001)

        yield {"type": "message_complete", "finish_reason": "stop"}


class AIAgentConversationEngine:
    """Manages session lifecycle, prompt submission, and history appending."""

    def __init__(self, provider: DeterministicSyntheticProvider) -> None:
        self.provider = provider
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.idempotency_map: Dict[str, str] = {}
        self._next_id: int = 0

    def create_session(
        self,
        profile_id: str,
        idempotency_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        if idempotency_key and idempotency_key in self.idempotency_map:
            sid = self.idempotency_map[idempotency_key]
            return {
                "session_id": sid,
                "reused": True,
                "profile_id": self.sessions[sid]["profile_id"],
                "message_count": len(self.sessions[sid]["history"]),
            }

        self._next_id += 1
        sid = f"sess-{profile_id}-{self._next_id}"
        session = {
            "session_id": sid,
            "profile_id": profile_id,
            "title": title or "Untitled Session",
            "state": "idle",
            "submit_status": "idle",
            "history": [],
            "uncertain_latch": False,
            "interrupt_event": asyncio.Event(),
            "pending_tool_calls": {},
        }
        self.sessions[sid] = session
        if idempotency_key:
            self.idempotency_map[idempotency_key] = sid

        return {
            "session_id": sid,
            "reused": False,
            "profile_id": profile_id,
            "message_count": 0,
        }

    def _get_session(self, session_id: str, profile_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            raise KeyError(f"Session '{session_id}' not found")
        session = self.sessions[session_id]
        if session["profile_id"] != profile_id:
            raise PermissionError(
                f"Profile mismatch: session belongs to '{session['profile_id']}', but request received from '{profile_id}'"
            )
        return session

    async def submit_prompt(
        self,
        session_id: str,
        profile_id: str,
        text: str,
        is_manual_retry: bool = False,
        on_delta: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        session = self._get_session(session_id, profile_id)

        # Transport Ambiguity Fencing (Uncertain-Submit Defense)
        if session["uncertain_latch"] and not is_manual_retry:
            raise ValueError(
                f"Session '{session_id}' is in UNCERTAIN state due to transport disruption. "
                "Automatic replay is strictly prohibited; manual re-submission is required."
            )

        if session["state"] in ("connecting", "streaming", "awaiting_tool"):
            raise RuntimeError(f"Session '{session_id}' is busy executing a turn.")

        session["uncertain_latch"] = False
        session["state"] = "connecting"
        session["submit_status"] = "in_flight"
        session["interrupt_event"].clear()

        # Append authoritative user turn
        session["history"].append({"role": "user", "content": text})

        assembled_text: List[str] = []
        finish_reason = "stop"

        try:
            session["state"] = "streaming"
            async for event in self.provider.stream_completion(
                text, session["interrupt_event"]
            ):
                if on_delta:
                    on_delta(event)

                event_type = event.get("type")
                if event_type == "text_delta":
                    assembled_text.append(event["text"])
                elif event_type == "tool_call":
                    session["state"] = "awaiting_tool"
                    session["pending_tool_calls"][event["id"]] = event
                elif event_type == "interrupted":
                    finish_reason = "interrupted"
                    session["state"] = "idle"
                    session["submit_status"] = "interrupted"
                    partial = "".join(assembled_text)
                    if partial:
                        session["history"].append(
                            {"role": "assistant", "content": f"{partial} [interrupted]"}
                        )
                    return {
                        "status": "interrupted",
                        "partial_text": partial,
                        "history_count": len(session["history"]),
                    }
                elif event_type == "message_complete":
                    finish_reason = event.get("finish_reason", "stop")

            # Finalize turn if not in tool awaiting state
            if session["state"] != "awaiting_tool":
                full_reply = "".join(assembled_text)
                session["history"].append(
                    {"role": "assistant", "content": full_reply}
                )
                session["state"] = "idle"
                session["submit_status"] = "completed"
                return {
                    "status": "completed",
                    "full_text": full_reply,
                    "finish_reason": finish_reason,
                    "history_count": len(session["history"]),
                }
            else:
                return {
                    "status": "awaiting_tool",
                    "pending_tools": list(session["pending_tool_calls"].keys()),
                }

        except Exception as exc:
            session["state"] = "idle"
            session["submit_status"] = "failed"
            # Render raw error faithfully
            return {
                "status": "error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    def resolve_tool(
        self, session_id: str, profile_id: str, tool_id: str, output: str
    ) -> None:
        session = self._get_session(session_id, profile_id)
        if tool_id not in session["pending_tool_calls"]:
            raise KeyError(f"Tool call '{tool_id}' not pending")

        call = session["pending_tool_calls"].pop(tool_id)
        session["history"].append(
            {"role": "assistant", "content": "", "tool_calls": [call]}
        )
        session["history"].append(
            {"role": "tool", "content": output, "tool_call_id": tool_id}
        )

        if not session["pending_tool_calls"]:
            session["state"] = "idle"
            session["submit_status"] = "completed"

    def interrupt(self, session_id: str, profile_id: str) -> Dict[str, Any]:
        session = self._get_session(session_id, profile_id)
        if session["state"] in ("connecting", "streaming", "awaiting_tool"):
            session["interrupt_event"].set()
            session["pending_tool_calls"].clear()
            session["state"] = "idle"
            session["submit_status"] = "interrupted"
            return {"interrupted": True}
        return {"interrupted": False}

    def trigger_network_drop(self, session_id: str, profile_id: str) -> None:
        session = self._get_session(session_id, profile_id)
        if session["submit_status"] == "in_flight":
            session["submit_status"] = "uncertain"
            session["uncertain_latch"] = True
            session["state"] = "idle"

    def get_history(self, session_id: str, profile_id: str) -> List[Dict[str, Any]]:
        session = self._get_session(session_id, profile_id)
        return list(session["history"])


# ==============================================================================
# UI State Machine Driver Simulation
# ==============================================================================


class UIConversationStateMachine:
    """Models UI state machine transitions: idle -> connecting -> streaming -> awaiting_tool -> idle."""

    def __init__(self) -> None:
        self.state = "idle"
        self.transition_log: List[str] = ["idle"]
        self.assembled_text: List[str] = []
        self.expected_chunk = 0
        self.buffer: Dict[int, str] = {}

    def transition_to(self, new_state: str) -> None:
        self.state = new_state
        self.transition_log.append(new_state)

    def on_submit(self) -> None:
        self.transition_to("connecting")

    def on_chunk(self, index: int, text: str) -> str:
        if self.state in ("connecting", "streaming"):
            if self.state != "streaming":
                self.transition_to("streaming")

        self.buffer[index] = text
        while self.expected_chunk in self.buffer:
            self.assembled_text.append(self.buffer.pop(self.expected_chunk))
            self.expected_chunk += 1

        return "".join(self.assembled_text)

    def on_tool_call(self) -> None:
        self.transition_to("awaiting_tool")

    def on_complete(self) -> None:
        self.transition_to("idle")


# ==============================================================================
# Test Cases
# ==============================================================================


@pytest.fixture
def engine() -> AIAgentConversationEngine:
    provider = DeterministicSyntheticProvider()
    return AIAgentConversationEngine(provider)


@pytest.mark.asyncio
async def test_session_create_idempotency_and_initial_state(
    engine: AIAgentConversationEngine,
) -> None:
    # 1. Create first session with idempotency key
    res1 = engine.create_session("profile-1", idempotency_key="key-abc", title="Main Chat")
    sid1 = res1["session_id"]
    assert not res1["reused"]
    assert res1["message_count"] == 0

    # 2. Re-create with same idempotency key returns identical session
    res2 = engine.create_session("profile-1", idempotency_key="key-abc", title="Main Chat")
    assert res2["session_id"] == sid1
    assert res2["reused"]

    # 3. Create with distinct idempotency key allocates distinct session
    res3 = engine.create_session("profile-1", idempotency_key="key-xyz", title="Other Chat")
    assert res3["session_id"] != sid1
    assert not res3["reused"]


@pytest.mark.asyncio
async def test_prompt_submit_deterministic_stream_and_authoritative_history(
    engine: AIAgentConversationEngine,
) -> None:
    session = engine.create_session("profile-1")
    sid = session["session_id"]

    deltas: List[Dict[str, Any]] = []

    result = await engine.submit_prompt(
        sid, "profile-1", "hello", on_delta=lambda d: deltas.append(d)
    )

    assert result["status"] == "completed"
    assert result["full_text"] == "Hello there, human!"
    assert result["finish_reason"] == "stop"

    # Verify deltas arrived in monotonic order
    text_deltas = [d for d in deltas if d["type"] == "text_delta"]
    assert len(text_deltas) == 3
    for i, delta in enumerate(text_deltas):
        assert delta["chunk_index"] == i

    # Verify authoritative history appending
    history = engine.get_history(sid, "profile-1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hello there, human!"


@pytest.mark.asyncio
async def test_raw_error_rendering_when_provider_fails(
    engine: AIAgentConversationEngine,
) -> None:
    engine.provider.should_fail = True
    session = engine.create_session("profile-1")
    sid = session["session_id"]

    result = await engine.submit_prompt(sid, "profile-1", "test fail")

    assert result["status"] == "error"
    assert result["error_type"] == "SyntheticProviderError"
    assert "Synthetic upstream provider error 503" in result["error_message"]


@pytest.mark.asyncio
async def test_ui_state_machine_transitions_and_ordered_assembly() -> None:
    ui = UIConversationStateMachine()
    assert ui.state == "idle"

    # idle -> connecting
    ui.on_submit()
    assert ui.state == "connecting"

    # connecting -> streaming (chunks out of order)
    ui.on_chunk(1, " World")
    assert ui.state == "streaming"
    assert "".join(ui.assembled_text) == ""  # Chunk 0 still pending

    ui.on_chunk(0, "Hello")
    assert "".join(ui.assembled_text) == "Hello World"

    # streaming -> awaiting_tool
    ui.on_tool_call()
    assert ui.state == "awaiting_tool"

    # awaiting_tool -> idle
    ui.on_complete()
    assert ui.state == "idle"

    assert ui.transition_log == [
        "idle",
        "connecting",
        "streaming",
        "awaiting_tool",
        "idle",
    ]


@pytest.mark.asyncio
async def test_uncertain_submit_defense_rejects_auto_replay(
    engine: AIAgentConversationEngine,
) -> None:
    session = engine.create_session("profile-1")
    sid = session["session_id"]

    # Start a submit task
    submit_task = asyncio.create_task(
        engine.submit_prompt(sid, "profile-1", "compute")
    )
    # Simulate network drop during in-flight submission
    await asyncio.sleep(0.0005)
    engine.trigger_network_drop(sid, "profile-1")

    # Await completion of original task
    await submit_task

    # Defense 1: Automatic replay without manual retry flag MUST be rejected
    with pytest.raises(ValueError, match="UNCERTAIN state"):
        await engine.submit_prompt(sid, "profile-1", "compute", is_manual_retry=False)

    # Defense 2: Explicit manual retry succeeds
    retry_result = await engine.submit_prompt(
        sid, "profile-1", "compute", is_manual_retry=True
    )
    assert retry_result["status"] == "completed"
    assert "Result is 42." in retry_result["full_text"]


@pytest.mark.asyncio
async def test_session_interrupt_and_abort_signal(
    engine: AIAgentConversationEngine,
) -> None:
    session = engine.create_session("profile-1")
    sid = session["session_id"]

    # Trigger interruption mid-stream
    async def trigger_interrupt_delayed():
        await asyncio.sleep(0.001)
        engine.interrupt(sid, "profile-1")

    asyncio.create_task(trigger_interrupt_delayed())

    result = await engine.submit_prompt(sid, "profile-1", "hello")
    assert result["status"] == "interrupted"

    # Authoritative history records interrupted turn
    history = engine.get_history(sid, "profile-1")
    assert len(history) == 2
    assert "[interrupted]" in history[1]["content"]

    # Subsequent interrupt on idle returns not interrupted
    idle_res = engine.interrupt(sid, "profile-1")
    assert not idle_res["interrupted"]


@pytest.mark.asyncio
async def test_profile_fencing_prevents_cross_profile_leakage(
    engine: AIAgentConversationEngine,
) -> None:
    # Alice creates session
    alice_sess = engine.create_session("profile-alice", title="Alice Vault")
    alice_sid = alice_sess["session_id"]
    await engine.submit_prompt(alice_sid, "profile-alice", "Alice confidential data")

    # 1. Bob attempts to access Alice's history -> REJECTED
    with pytest.raises(PermissionError, match="Profile mismatch"):
        engine.get_history(alice_sid, "profile-bob")

    # 2. Bob attempts to submit prompt to Alice's session -> REJECTED
    with pytest.raises(PermissionError, match="Profile mismatch"):
        await engine.submit_prompt(alice_sid, "profile-bob", "Bob tampering")

    # 3. Bob attempts to interrupt Alice's session -> REJECTED
    with pytest.raises(PermissionError, match="Profile mismatch"):
        engine.interrupt(alice_sid, "profile-bob")

    # 4. Alice can read her own history without interference
    alice_history = engine.get_history(alice_sid, "profile-alice")
    assert len(alice_history) == 2
    assert alice_history[0]["content"] == "Alice confidential data"
