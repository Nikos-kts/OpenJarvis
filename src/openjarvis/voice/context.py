"""Conversation context for the voice pipeline.

Holds turn-level history (utterances + assistant responses) in memory so
that the context survives provider failover mid-conversation. The context
is intentionally lightweight — it does not perform retrieval or
compression; those are the responsibility of the existing LLM layer if
higher-level orchestration is needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class Turn:
    """One exchange in the voice conversation."""

    role: str  # "user" | "assistant"
    text: str
    ts: float = field(default_factory=time.monotonic)
    provider: str = ""  # which provider produced this turn


class ConversationContext:
    """Maintains rolling turn history for a voice session.

    Thread-safe for concurrent read/append (GIL is sufficient since every
    operation is a single Python list mutation).
    """

    def __init__(self, max_turns: int = 40) -> None:
        self._max_turns = max_turns
        self._turns: List[Turn] = []
        self.session_id: str = ""
        self.provider: str = ""
        self.started_at: float = time.monotonic()

    # ---- mutators -----------------------------------------------------------

    def add_user(self, text: str, provider: str = "") -> None:
        self._append(Turn(role="user", text=text, provider=provider))

    def add_assistant(self, text: str, provider: str = "") -> None:
        self._append(Turn(role="assistant", text=text, provider=provider))

    def _append(self, turn: Turn) -> None:
        self._turns.append(turn)
        # Evict oldest pairs first so max_turns is honoured.
        while len(self._turns) > self._max_turns:
            self._turns.pop(0)

    def clear(self) -> None:
        self._turns.clear()

    # ---- accessors ----------------------------------------------------------

    @property
    def turns(self) -> List[Turn]:
        return list(self._turns)

    def last_n(self, n: int) -> List[Turn]:
        return list(self._turns[-n:])

    def to_messages(self) -> List[dict]:
        """Format turns as a list of ``{"role": ..., "content": ...}`` dicts
        suitable for injection into a chat-completion-style prompt."""
        return [{"role": t.role, "content": t.text} for t in self._turns]

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "turns": len(self._turns),
            "duration_s": round(time.monotonic() - self.started_at, 1),
        }

    # ---- serialization (for websocket events) -------------------------------

    def last_user_text(self) -> Optional[str]:
        for t in reversed(self._turns):
            if t.role == "user":
                return t.text
        return None

    def last_assistant_text(self) -> Optional[str]:
        for t in reversed(self._turns):
            if t.role == "assistant":
                return t.text
        return None
