"""Jarvis — the primary agent and mastermind of OpenJarvis.

Unlike the generic ``AgentRegistry`` harnesses (``simple``,
``orchestrator``, ``native_react`` …) which are **internal
implementation details** used by sub-agents, Jarvis is a first-class
singleton with its own persona, state, and REST namespace (``/v1/jarvis/*``).

Users never pick between harnesses any more: the main chat talks to
Jarvis, and Jarvis decides when to delegate to a sub-agent created in
the Agents UI.  Sub-agents are stored in ``.openJarvis/db/agents.db``;
Jarvis's own state lives separately in ``.openJarvis/db/jarvis.db``.

Module layout
-------------
- :mod:`openjarvis.jarvis.agent`       — the :class:`JarvisAgent` class.
- :mod:`openjarvis.jarvis.persona`     — loads SOUL / MEMORY / USER and
  assembles the Jarvis system prompt.
- :mod:`openjarvis.jarvis.delegation`  — sub-agent router and the
  ``delegate_to_subagent`` tool.
- :mod:`openjarvis.jarvis.state_store` — SQLite-backed runtime state
  (mood, metrics, delegation log).
- :mod:`openjarvis.jarvis.routes`      — FastAPI router mounted at
  ``/v1/jarvis``.
"""

from __future__ import annotations

from openjarvis.jarvis.agent import JarvisAgent
from openjarvis.jarvis.factory import build_jarvis_agent
from openjarvis.jarvis.persona import JarvisPersona, PersonaSnapshot
from openjarvis.jarvis.state_store import JarvisStateStore

__all__ = [
    "JarvisAgent",
    "JarvisPersona",
    "PersonaSnapshot",
    "JarvisStateStore",
    "build_jarvis_agent",
]
