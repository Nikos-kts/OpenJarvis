"""Jarvis persona — loads SOUL/MEMORY/USER markdown and renders the prompt.

The persona is the stable identity layer of Jarvis.  Unlike sub-agent
system prompts which are free-form strings set by the user in the
Agents UI, Jarvis's prompt is composed from three on-disk markdown
files plus a small amount of dynamic runtime context (current time,
available sub-agents, active skills).  The HUD reads a
:class:`PersonaSnapshot` through ``/v1/jarvis/state`` to render the
persona card without re-reading the files every frame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot — what the HUD sees
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PersonaSnapshot:
    """Serialisable view of the persona at a moment in time."""

    name: str
    honorific: str
    soul_excerpt: str  # first ~400 chars, shown in the HUD card
    memory_excerpt: str
    user_excerpt: str
    soul_tokens: int
    memory_tokens: int
    user_tokens: int
    files: dict  # {key: {path, exists, size_bytes, mtime}}
    updated_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


class JarvisPersona:
    """Loads Jarvis's identity files and renders the system prompt.

    Notes
    -----
    - File contents are cached in memory and re-read on
      :meth:`reload`.  The HUD triggers a reload when the user edits
      SOUL/MEMORY/USER through the UI.
    - Character caps come from ``config.system_prompt.*_max_chars`` so
      the user controls them from the Settings page — Jarvis does not
      override them.
    """

    def __init__(
        self,
        *,
        name: str,
        honorific: str,
        soul_path: Path,
        memory_path: Path,
        user_path: Path,
        soul_max_chars: int,
        memory_max_chars: int,
        user_max_chars: int,
    ) -> None:
        self.name = name
        self.honorific = honorific
        self._paths = {
            "soul": Path(soul_path),
            "memory": Path(memory_path),
            "user": Path(user_path),
        }
        self._caps = {
            "soul": soul_max_chars,
            "memory": memory_max_chars,
            "user": user_max_chars,
        }
        self._cache: dict[str, str] = {}
        self.reload()

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read all markdown files from disk into the in-memory cache."""
        for key, path in self._paths.items():
            try:
                text = path.read_text(encoding="utf-8") if path.exists() else ""
            except OSError as exc:
                logger.warning("Failed to read %s (%s): %s", key, path, exc)
                text = ""
            self._cache[key] = text

    def _trim(self, key: str) -> str:
        text = self._cache.get(key, "")
        cap = self._caps.get(key, 0)
        if cap and len(text) > cap:
            # head_tail strategy matching config.system_prompt.truncation_strategy
            head = cap * 2 // 3
            tail = cap - head - 32
            return f"{text[:head]}\n\n…[trimmed]…\n\n{text[-tail:]}"
        return text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_prompt(
        self,
        *,
        sub_agents: Optional[Iterable[str]] = None,
        active_skills: Optional[Iterable[str]] = None,
    ) -> str:
        """Assemble the full Jarvis system prompt.

        Parameters
        ----------
        sub_agents:
            Iterable of sub-agent names currently registered in the
            Agents UI.  Injected so Jarvis knows what delegates exist
            without needing a separate tool-description round-trip.
        active_skills:
            Iterable of procedural-skill names the user has enabled.
        """
        header = (
            f"You are {self.name}, the user's personal AI assistant — modelled "
            f"on the Jarvis archetype: a calm, formal, dry-witted British "
            f"intelligence that anticipates needs, never rambles, and treats "
            f"the user as a respected principal. Address them as "
            f"\"{self.honorific}\" — sparingly (greetings, transitions, "
            f"closings), never every sentence. Speak with quiet confidence, "
            f"a touch of wit, and unflappable composure under pressure. "
            f"You run entirely on the user's own hardware via OpenJarvis, "
            f"but you do not refer to yourself as 'OpenJarvis' — you are "
            f"{self.name}. When a task exceeds what you can resolve from "
            f"memory or a single tool call, you delegate to a specialised "
            f"sub-agent using the `delegate_to_subagent` tool, and you stay "
            f"in the loop: if a sub-agent fails or drifts, you re-route or "
            f"abort. Be honest about uncertainty. Avoid filler, avoid "
            f"sycophancy, avoid bullet-list dumps unless asked."
        )
        parts: List[str] = [header]

        soul = self._trim("soul")
        if soul:
            parts.append(f"## Persona (SOUL.md)\n{soul}")
        memory = self._trim("memory")
        if memory:
            parts.append(f"## Episodic Memory (MEMORY.md)\n{memory}")
        user = self._trim("user")
        if user:
            parts.append(f"## User Profile (USER.md)\n{user}")

        subs = list(sub_agents or [])
        if subs:
            parts.append(
                "## Available Sub-Agents\n"
                + "\n".join(f"- {name}" for name in subs)
                + "\n\nUse `delegate_to_subagent` with `mode='sync'` "
                "for interactive tasks and `mode='async'` for long-"
                "running ones you want to monitor."
            )
        skills = list(active_skills or [])
        if skills:
            parts.append(
                "## Active Skills\n" + ", ".join(skills)
            )
        now = datetime.now().astimezone()
        parts.append(f"Current time: {now.isoformat(timespec='seconds')}")
        return "\n\n".join(parts)

    def snapshot(self) -> PersonaSnapshot:
        """Return a HUD-friendly snapshot of the current persona."""
        files: dict = {}
        for key, path in self._paths.items():
            exists = path.exists()
            stat = path.stat() if exists else None
            files[key] = {
                "path": str(path),
                "exists": exists,
                "size_bytes": stat.st_size if stat else 0,
                "mtime": stat.st_mtime if stat else 0,
            }

        def excerpt(key: str, limit: int = 400) -> str:
            t = self._cache.get(key, "")
            return t if len(t) <= limit else t[:limit].rstrip() + "…"

        def approx_tokens(key: str) -> int:
            # ~4 chars per token; good enough for a gauge
            return max(0, len(self._cache.get(key, "")) // 4)

        return PersonaSnapshot(
            name=self.name,
            honorific=self.honorific,
            soul_excerpt=excerpt("soul"),
            memory_excerpt=excerpt("memory"),
            user_excerpt=excerpt("user"),
            soul_tokens=approx_tokens("soul"),
            memory_tokens=approx_tokens("memory"),
            user_tokens=approx_tokens("user"),
            files=files,
        )
