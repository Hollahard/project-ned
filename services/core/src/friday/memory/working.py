"""Working memory tier: Ephemeral in-turn scratchpad for Friday."""

from typing import List


class WorkingMemory:
    """Ephemeral in-memory scratchpad for the active agent turn."""

    def __init__(self) -> None:
        self._notes: List[str] = []

    def add_note(self, note: str) -> None:
        clean = note.strip()
        if clean:
            self._notes.append(clean)

    def get_notes(self) -> List[str]:
        return list(self._notes)

    def clear(self) -> None:
        self._notes.clear()

    def format_summary(self, max_chars: int = 1000) -> str:
        if not self._notes:
            return ""
        text = "\n".join(f"- {note}" for note in self._notes)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[Working notes truncated]"
        return text
