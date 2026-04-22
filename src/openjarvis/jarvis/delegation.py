"""Sub-agent delegation — the `delegate_to_subagent` tool for Jarvis.

Jarvis stays in the loop: ``mode='sync'`` blocks and returns the sub-
agent's final answer as the tool result; ``mode='async'`` spawns a
background thread, returns a delegation handle immediately, and pushes
progress events to the bus for the HUD.

Targets are the managed sub-agents stored in
``.openJarvis/db/agents.db`` via :class:`AgentManager`.  Each managed
agent carries an ``agent_type`` (a registry key such as ``simple`` or
``orchestrator``), a ``config`` dict (model, tools, system_prompt) and
a display ``name``.  The delegation path intentionally mirrors
:meth:`AgentExecutor._invoke_agent` so behaviour is consistent
between scheduled ticks and Jarvis-initiated one-shots.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult
from openjarvis.jarvis.state_store import JarvisStateStore
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


class DelegateToSubAgentTool(BaseTool):
    """Tool surface for ``delegate_to_subagent``.

    Parameters
    ----------
    manager:
        :class:`openjarvis.agents.manager.AgentManager`.
    system:
        Object exposing ``engine``, ``model`` (and optionally ``bus``).
        Needed to instantiate the sub-agent.
    store:
        :class:`JarvisStateStore` for the delegation log.
    bus:
        Event bus for real-time HUD updates (optional).
    """

    tool_id = "delegate_to_subagent"

    def __init__(
        self,
        *,
        manager: Any,
        system: Any,
        store: JarvisStateStore,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._manager = manager
        self._system = system
        self._store = store
        self._bus = bus

    # ------------------------------------------------------------------
    # ToolSpec
    # ------------------------------------------------------------------

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="delegate_to_subagent",
            description=(
                "Delegate a task to a specialised sub-agent managed "
                "by the user. Use this when the task is outside your "
                "core capabilities, would benefit from a focused "
                "persona, or when the user asks you to route work to "
                "a specific agent by name. Provide a self-contained "
                "brief — the sub-agent does not see the main "
                "conversation. In sync mode you receive the sub-"
                "agent's final answer as the tool result. In async "
                "mode you receive a delegation id immediately; "
                "progress streams to the user while you continue."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": (
                            "Sub-agent name or id as registered in "
                            "the Agents UI."
                        ),
                    },
                    "brief": {
                        "type": "string",
                        "description": (
                            "Self-contained task description for the "
                            "sub-agent. Include all context it needs."
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["sync", "async"],
                        "description": (
                            "'sync' waits for completion; 'async' "
                            "returns a handle and runs in background."
                        ),
                    },
                },
                "required": ["agent", "brief"],
            },
            category="delegation",
            latency_estimate=5.0,
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, **params: Any) -> ToolResult:
        target = str(params.get("agent") or params.get("agent_id") or "").strip()
        brief = str(params.get("brief", "")).strip()
        mode = str(params.get("mode", "sync")).strip().lower()
        if mode not in ("sync", "async"):
            mode = "sync"

        if not target or not brief:
            return ToolResult(
                tool_name=self.tool_id,
                content="delegate_to_subagent: both 'agent' and 'brief' are required.",
                success=False,
            )

        agent_dict = self._resolve(target)
        if agent_dict is None:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"No sub-agent matching '{target}'. "
                    f"Known: {', '.join(self._known_names()) or '(none registered)'}"
                ),
                success=False,
            )

        if not self._is_allowed(agent_dict):
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"Sub-agent '{agent_dict.get('name', target)}' is not in the "
                    "delegation allowlist. Enable it from the HUD Capabilities "
                    "→ Configure Agents dialog before delegating."
                ),
                success=False,
            )

        delegation_id = f"dlg_{uuid.uuid4().hex[:12]}"
        self._store.start_delegation(
            delegation_id=delegation_id,
            sub_agent=agent_dict.get("name", target),
            brief=brief,
            mode=mode,
        )
        self._emit(
            "jarvis_delegation_start",
            {
                "delegation_id": delegation_id,
                "sub_agent": agent_dict.get("name", target),
                "agent_id": agent_dict.get("id"),
                "mode": mode,
            },
        )

        if mode == "async":
            threading.Thread(
                target=self._run_sync,
                name=f"jarvis-delegate-{delegation_id}",
                args=(delegation_id, agent_dict, brief),
                daemon=True,
            ).start()
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"Delegated to '{agent_dict.get('name', target)}' in "
                    f"background. Handle: {delegation_id}. Progress "
                    "streams to the user; continue the conversation "
                    "and look for a completion event."
                ),
                success=True,
                metadata={"delegation_id": delegation_id, "mode": "async"},
            )

        return self._run_sync(delegation_id, agent_dict, brief)

    # ------------------------------------------------------------------
    # Sub-agent invocation (mirrors AgentExecutor._invoke_agent)
    # ------------------------------------------------------------------

    def _run_sync(
        self,
        delegation_id: str,
        agent_dict: dict,
        brief: str,
    ) -> ToolResult:
        sub_name = agent_dict.get("name", "?")
        try:
            content = self._invoke(agent_dict, brief)
        except Exception as exc:
            logger.exception("Delegation %s failed", delegation_id)
            self._store.finish_delegation(
                delegation_id,
                status="failed",
                error=str(exc),
            )
            self._emit(
                "jarvis_delegation_end",
                {
                    "delegation_id": delegation_id,
                    "status": "failed",
                    "error": str(exc),
                },
            )
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Sub-agent '{sub_name}' failed: {exc}",
                success=False,
                metadata={"delegation_id": delegation_id},
            )

        self._store.finish_delegation(
            delegation_id,
            status="completed",
            result_summary=content[:2000],
        )
        self._emit(
            "jarvis_delegation_end",
            {"delegation_id": delegation_id, "status": "completed"},
        )
        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=True,
            metadata={"delegation_id": delegation_id},
        )

    def _invoke(self, agent_dict: dict, brief: str) -> str:
        from openjarvis.core.registry import AgentRegistry, ToolRegistry

        agent_type = agent_dict.get("agent_type", "orchestrator")
        try:
            agent_cls = AgentRegistry.get(agent_type)
        except KeyError:
            raise RuntimeError(f"Unknown agent_type '{agent_type}'") from None

        cfg = agent_dict.get("config", {}) or {}

        engine = getattr(self._system, "engine", None)
        if engine is None:
            raise RuntimeError("System has no engine available for delegation")
        model = cfg.get("model") or getattr(self._system, "model", "") or ""
        if not model:
            raise RuntimeError("No model configured for sub-agent or system")

        # Resolve tools
        tool_names = cfg.get("tools", [])
        if isinstance(tool_names, str):
            tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]
        tool_instances: List[Any] = []
        for tname in tool_names:
            if ToolRegistry.contains(tname):
                try:
                    tool_cls = ToolRegistry.get(tname)
                    tool_instances.append(tool_cls())
                except Exception:
                    logger.debug("Failed to instantiate sub-agent tool %s", tname)

        agent_kwargs: dict[str, Any] = {"bus": self._bus}
        sys_prompt = cfg.get("system_prompt")
        if sys_prompt:
            agent_kwargs["system_prompt"] = sys_prompt
        if getattr(agent_cls, "accepts_tools", False) and tool_instances:
            agent_kwargs["tools"] = tool_instances

        try:
            instance = agent_cls(engine, model, **agent_kwargs)
        except TypeError:
            instance = agent_cls(engine, model)

        result = instance.run(brief)
        return getattr(result, "content", None) or str(result)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _resolve(self, target: str) -> Optional[dict]:
        """Find a managed agent by id or name (case-insensitive)."""
        getter = getattr(self._manager, "get_agent", None)
        if callable(getter):
            try:
                got = getter(target)
            except Exception:
                got = None
            if got:
                return got

        lister = getattr(self._manager, "list_agents", None)
        if not callable(lister):
            return None
        try:
            candidates = lister() or []
        except Exception:
            return None
        wanted = target.lower()
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            name = (cand.get("name") or "").lower()
            cid = (cand.get("id") or "").lower()
            if wanted in (name, cid):
                return cand
        return None

    def _known_names(self) -> List[str]:
        lister = getattr(self._manager, "list_agents", None)
        if not callable(lister):
            return []
        try:
            return [a.get("name", "") for a in (lister() or []) if isinstance(a, dict)]
        except Exception:
            return []

    def _is_allowed(self, agent_dict: dict) -> bool:
        """Consult the persisted delegation allowlist.

        ``None`` / missing means "unrestricted".  Otherwise only
        agents whose id or name appears in the list are delegatable.
        """
        try:
            allow = self._store.get("active_agents", None)
        except Exception:
            return True
        if not isinstance(allow, list):
            return True
        wanted = {str(x) for x in allow}
        return (
            str(agent_dict.get("id") or "") in wanted
            or str(agent_dict.get("name") or "") in wanted
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit(self, kind: str, payload: dict) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(EventType.AGENT_TURN_END, {"kind": kind, **payload})
        except Exception:
            logger.debug("Failed to publish delegation event %s", kind, exc_info=True)


def build_delegate_tool(
    *,
    manager: Any,
    system: Any,
    store: JarvisStateStore,
    bus: Optional[EventBus] = None,
) -> Optional[DelegateToSubAgentTool]:
    """Return a :class:`DelegateToSubAgentTool` or ``None`` when
    prerequisites (manager or engine on the system) are absent.
    """
    if manager is None or system is None:
        return None
    if getattr(system, "engine", None) is None:
        return None
    return DelegateToSubAgentTool(
        manager=manager,
        system=system,
        store=store,
        bus=bus,
    )
