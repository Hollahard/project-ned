"""Context budget manager and history compaction for Project Friday.

Invariants:
1. Tool outputs are aggressively truncated to conserve model context.
2. Conversation history is compacted via a sliding window preserving the system prompt
   and recent turns.
3. Total token estimation ensures turns never exceed model context windows.
"""

import logging
from typing import List
from friday.inference.protocol import ChatMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_TOKENS = 32768
DEFAULT_MAX_TOOL_CHARS = 4000
DEFAULT_KEEP_RECENT = 4


class ContextBudget:
    """Manages token estimation, tool output truncation, and conversation compaction."""

    def __init__(
        self,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
        keep_recent: int = DEFAULT_KEEP_RECENT,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.max_tool_chars = max_tool_chars
        self.keep_recent = keep_recent

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count using a standard ~3.8-4 chars/token heuristic."""
        if not text:
            return 0
        # Heuristic: 1 token ~ 3.8 characters + 1 overhead per message
        return max(1, int(len(text) / 3.8)) + 1

    def estimate_message_tokens(self, message: ChatMessage) -> int:
        """Estimate total tokens consumed by a single ChatMessage."""
        total = self.estimate_tokens(message.content)
        if message.tool_calls:
            import json
            tc_str = json.dumps(message.tool_calls)
            total += self.estimate_tokens(tc_str)
        return total

    def estimate_history_tokens(self, messages: List[ChatMessage]) -> int:
        """Estimate total tokens consumed by an entire message sequence."""
        return sum(self.estimate_message_tokens(m) for m in messages)

    def truncate_tool_output(self, content: str, max_chars: int | None = None) -> str:
        """Aggressively truncate long tool outputs to avoid bloating context."""
        limit = max_chars or self.max_tool_chars
        if len(content) <= limit:
            return content

        excess = len(content) - limit
        half = limit // 2
        prefix = content[:half]
        suffix = content[-half:] if half > 0 else ""
        notice = f"\n\n[... Truncated {excess} characters to conserve context budget ...]\n\n"
        logger.info("Truncated tool output from %d to %d chars", len(content), limit)
        return prefix + notice + suffix

    def compact_history(
        self,
        messages: List[ChatMessage],
        budget_tokens: int | None = None,
        keep_recent: int | None = None,
    ) -> List[ChatMessage]:
        """Compact conversation history to strictly fit within budget.

        Strategy:
        1. Always preserve system message if present at index 0.
        2. Always preserve the most recent `keep_recent` messages.
        3. Compact/prune intermediate messages from oldest to newest until under budget.
        """
        budget = budget_tokens or self.max_context_tokens
        recent_count = keep_recent or self.keep_recent

        if not messages:
            return []

        total_tokens = self.estimate_history_tokens(messages)
        if total_tokens <= budget:
            return list(messages)

        # Separate system prompt if first message is system
        has_system = messages[0].role == "system"
        system_msg = [messages[0]] if has_system else []
        conversation = messages[1:] if has_system else messages

        if len(conversation) <= recent_count:
            # Cannot prune fewer than recent_count; return as is
            return system_msg + conversation

        recent_msgs = conversation[-recent_count:]
        older_msgs = conversation[:-recent_count]

        # Compact older messages
        pruned_count = 0
        preserved_older: List[ChatMessage] = []

        # Iterate older messages from newest to oldest to see what fits
        current_tokens = self.estimate_history_tokens(system_msg + recent_msgs)
        for msg in reversed(older_msgs):
            msg_tokens = self.estimate_message_tokens(msg)
            if current_tokens + msg_tokens <= budget - 100:  # 100 token buffer
                preserved_older.insert(0, msg)
                current_tokens += msg_tokens
            else:
                pruned_count += 1

        compacted: List[ChatMessage] = []
        compacted.extend(system_msg)

        if pruned_count > 0:
            summary_notice = ChatMessage(
                role="system",
                content=f"[Context compaction: {pruned_count} earlier turns compacted to remain within {budget} token budget]",
            )
            compacted.append(summary_notice)

        compacted.extend(preserved_older)
        compacted.extend(recent_msgs)

        logger.info(
            "Compacted history from %d to %d messages (tokens: %d -> %d)",
            len(messages),
            len(compacted),
            total_tokens,
            self.estimate_history_tokens(compacted),
        )
        return compacted

    def get_utilization(
        self, messages: List[ChatMessage], budget_tokens: int | None = None
    ) -> dict:
        """Returns context utilization percentage and token metrics."""
        budget = budget_tokens or self.max_context_tokens
        used = self.estimate_history_tokens(messages)
        pct = round((used / budget) * 100, 2) if budget > 0 else 0.0
        return {
            "estimated_tokens": used,
            "max_tokens": budget,
            "utilization_percent": pct,
            "remaining_tokens": max(0, budget - used),
        }
