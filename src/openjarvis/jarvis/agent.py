"""JarvisAgent — primary singleton agent.

``JarvisAgent`` is *not* registered with :class:`AgentRegistry`: it is
an explicit object built by the :class:`SystemBuilder` when
``config.jarvis.enabled`` is true, and assigned to ``app.state.agent``.
It composes an internal :class:`OrchestratorAgent` for the tool loop
and layers on:

1. A persona system prompt assembled from SOUL/MEMORY/USER.
2. A ``delegate_to_subagent`` tool that can invoke managed sub-agents
   either synchronously (wait for reply) or asynchronously (fire-and-
   stream-progress).
3. Persistent metrics via :class:`JarvisStateStore`.

The class deliberately implements the same interface as the other
agents (``run``/``accepts_tools``/``_tools``) so the existing chat
streaming bridge (``server.stream_bridge``) picks it up without
modification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.jarvis.persona import JarvisPersona
from openjarvis.jarvis.state_store import JarvisStateStore
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


class JarvisAgent(ToolUsingAgent):
    """The primary Jarvis agent.

    Parameters
    ----------
    engine, model:
        Inference backend (same as any other agent).
    tools:
        Core tools Jarvis always has.  The ``delegate_to_subagent``
        tool is appended automatically when *delegate_tool* is
        provided.
    persona:
        Pre-constructed :class:`JarvisPersona` (loaded by
        :class:`SystemBuilder`).
    store:
        :class:`JarvisStateStore` for metrics and delegation log.
    delegate_tool:
        Optional :class:`BaseTool` produced by
        :func:`openjarvis.jarvis.delegation.build_delegate_tool`.
    sub_agent_names:
        Names of currently registered managed sub-agents, injected
        into the system prompt so Jarvis knows what targets exist.
    active_skills:
        Names of enabled procedural skills, same rationale.
    """

    agent_id = "jarvis"
    _default_temperature = 0.5   # a bit more deterministic than generic
    _default_max_tokens = 2048
    _default_max_turns = 12

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        persona: JarvisPersona,
        store: JarvisStateStore,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        delegate_tool: Optional[BaseTool] = None,
        sub_agent_names: Optional[Iterable[str]] = None,
        active_skills: Optional[Iterable[str]] = None,
        default_active_tool_names: Optional[Iterable[str]] = None,
        sensitive_tool_names: Optional[Iterable[str]] = None,
        all_skills: Optional[List[Dict[str, Any]]] = None,
        interactive: bool = False,
    ) -> None:
        combined_tools: List[BaseTool] = list(tools or [])
        if delegate_tool is not None:
            combined_tools.append(delegate_tool)

        super().__init__(
            engine,
            model,
            tools=combined_tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
        )
        self._persona = persona
        self._store = store
        self._sub_agent_names = list(sub_agent_names or [])
        self._sensitive_tool_names = set(sensitive_tool_names or [])

        # Capabilities: the full universe of tools Jarvis can access
        # is frozen at construction time (``_all_tools``).  ``_tools``
        # is the *active* subset, derived from the persisted
        # ``active_tools`` KV entry.  When the entry is absent (first
        # run), we fall back to *default_active_tool_names* if given —
        # typically the caller's previously-used core toolset — so the
        # newly-exposed universe doesn't silently enable every tool.
        self._all_tools: List[BaseTool] = list(combined_tools)
        known_names = {t.spec.name for t in self._all_tools}
        persisted_active_tools = store.get("active_tools", None)
        if isinstance(persisted_active_tools, list):
            names = {str(n) for n in persisted_active_tools}
            self._active_tool_names = known_names & names
        elif default_active_tool_names is not None:
            wanted = {str(n) for n in default_active_tool_names}
            self._active_tool_names = known_names & wanted
        else:
            self._active_tool_names = set(known_names)
        self._tools = [t for t in self._all_tools if t.spec.name in self._active_tool_names]

        # Skills: same pattern — persisted overrides take precedence
        # over any caller-provided defaults.
        persisted_skills = store.get("active_skills", None)
        if isinstance(persisted_skills, list):
            self._active_skills = [str(s) for s in persisted_skills]
        else:
            self._active_skills = list(active_skills or [])

        # Full skill catalogue metadata (name / description / tags /
        # version / author / step count).  Populated from the filesystem
        # discovery pass by the factory; the HUD reads this via the
        # ``/v1/jarvis/skills`` endpoint so users can browse and toggle
        # every skill known to this process, not only currently-active
        # ones.
        self._all_skills: List[Dict[str, Any]] = list(all_skills or [])

        # Sub-agent delegation allowlist.  ``None`` (unset) means "all
        # known sub-agents are delegatable"; a list restricts
        # delegation to just those agent ids/names.
        persisted_agents = store.get("active_agents", None)
        if isinstance(persisted_agents, list):
            self._active_agents: Optional[List[str]] = [str(a) for a in persisted_agents]
        else:
            self._active_agents = None

        # Internal orchestrator does the actual work.  We rebuild it
        # lazily because SOUL/MEMORY/USER may change between turns.
        self._inner: Optional[OrchestratorAgent] = None

    # ------------------------------------------------------------------
    # Dynamic registration helpers (called by routes / builder)
    # ------------------------------------------------------------------

    def set_sub_agents(self, names: Iterable[str]) -> None:
        self._sub_agent_names = list(names)
        self._inner = None  # force rebuild with new prompt

    def set_active_skills(self, names: Iterable[str]) -> None:
        self._active_skills = list(names)
        self._store.set("active_skills", self._active_skills)
        self._inner = None

    def set_active_tools(self, names: Iterable[str]) -> None:
        """Filter the active toolset.  Persists and forces rebuild."""
        wanted = {str(n) for n in names}
        known = {t.spec.name for t in self._all_tools}
        self._active_tool_names = wanted & known
        self._tools = [t for t in self._all_tools if t.spec.name in self._active_tool_names]
        self._store.set("active_tools", sorted(self._active_tool_names))
        self._inner = None

    def set_active_agents(self, ids: Optional[Iterable[str]]) -> None:
        """Set the sub-agent delegation allowlist.

        Pass ``None`` to clear the allowlist (delegation becomes
        unrestricted).  Otherwise ``ids`` is the explicit list of
        agent ids/names that ``delegate_to_subagent`` will accept.
        """
        if ids is None:
            self._active_agents = None
            self._store.set("active_agents", None)
        else:
            self._active_agents = [str(a) for a in ids]
            self._store.set("active_agents", list(self._active_agents))
        self._inner = None

    def is_agent_allowed(self, agent: dict) -> bool:
        """Whether ``agent`` (a sub-agent record) may be delegated to."""
        if self._active_agents is None:
            return True
        wanted = set(self._active_agents)
        return (
            (agent.get("id") or "") in wanted
            or (agent.get("name") or "") in wanted
        )

    @property
    def all_tools(self) -> List[BaseTool]:
        """Full universe of tools Jarvis was built with (active or not)."""
        return list(self._all_tools)

    def reload_persona(self) -> None:
        self._persona.reload()
        self._inner = None

    @property
    def persona(self) -> JarvisPersona:
        return self._persona

    @property
    def store(self) -> JarvisStateStore:
        return self._store

    # ------------------------------------------------------------------
    # Core loop — delegates to an OrchestratorAgent with a fresh prompt
    # ------------------------------------------------------------------

    def _build_inner(self) -> OrchestratorAgent:
        system_prompt = self._persona.render_prompt(
            sub_agents=self._sub_agent_names,
            active_skills=self._active_skills,
        )
        return OrchestratorAgent(
            self._engine,
            self._model,
            tools=self._tools,
            bus=self._bus,
            max_turns=self._max_turns,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            mode="function_calling",
            system_prompt=system_prompt,
        )

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        logger.info(
            "JarvisAgent.run: input=%d chars tools=%d subs=%d",
            len(input),
            len(self._tools),
            len(self._sub_agent_names),
        )
        if self._inner is None:
            self._inner = self._build_inner()

        if self._bus is not None:
            self._bus.publish(
                EventType.AGENT_TURN_START,
                {"agent": self.agent_id, "input": input},
            )

        try:
            result = self._inner.run(input, context, **kwargs)
        except Exception:
            self._store.update_metrics(total_errors=1)
            self._store.log_event("turn_error", {"input": input[:200]})
            raise

        # Record metrics on success
        usage = result.metadata.get("usage", {}) if result.metadata else {}
        self._store.update_metrics(
            total_turns=1,
            total_tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            total_tokens_out=int(usage.get("completion_tokens", 0) or 0),
        )
        self._store.log_event(
            "turn_complete",
            {"turns": result.turns, "tool_calls": len(result.tool_results)},
        )
        return result
