"""Unit tests for ContextBudget manager."""

import pytest
from friday.sessions.budget import ContextBudget
from friday.inference.protocol import ChatMessage


def test_token_estimation_and_utilization():
    budget = ContextBudget(max_context_tokens=1000)
    text = "Hello world, this is a test sentence for token counting."
    tokens = budget.estimate_tokens(text)
    assert tokens > 5
    assert tokens < 30

    msg = ChatMessage(role="user", content=text)
    msg_tokens = budget.estimate_message_tokens(msg)
    assert msg_tokens == tokens

    util = budget.get_utilization([msg], budget_tokens=1000)
    assert util["estimated_tokens"] == tokens
    assert util["max_tokens"] == 1000
    assert util["utilization_percent"] > 0.0
    assert util["remaining_tokens"] == 1000 - tokens


def test_tool_output_truncation():
    budget = ContextBudget(max_tool_chars=200)

    short_out = "Short command output"
    assert budget.truncate_tool_output(short_out) == short_out

    long_out = "A" * 1000
    truncated = budget.truncate_tool_output(long_out)
    assert len(truncated) < 400
    assert "[... Truncated" in truncated
    assert "to conserve context budget ...]" in truncated


def test_sliding_window_compaction():
    # Set a small budget of 200 tokens
    budget = ContextBudget(max_context_tokens=200, keep_recent=4)

    messages = [ChatMessage(role="system", content="You are a helpful assistant.")]
    for i in range(50):
        messages.append(
            ChatMessage(
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}: This is detailed turn content with some information to take up token space.",
            )
        )

    initial_tokens = budget.estimate_history_tokens(messages)
    assert initial_tokens > 500  # Well over 200 tokens

    compacted = budget.compact_history(messages, budget_tokens=200, keep_recent=4)

    # Invariants:
    # 1. System prompt is preserved as message 0
    assert compacted[0].role == "system"
    assert compacted[0].content == "You are a helpful assistant."

    # 2. Most recent 4 messages are preserved at the end
    assert compacted[-4].content == messages[-4].content
    assert compacted[-3].content == messages[-3].content
    assert compacted[-2].content == messages[-2].content
    assert compacted[-1].content == messages[-1].content

    # 3. Compacted tokens are strictly within budget
    final_tokens = budget.estimate_history_tokens(compacted)
    assert final_tokens <= 200
