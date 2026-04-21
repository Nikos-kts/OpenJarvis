"""Delegation primitives — run another managed agent on behalf of Jarvis.

Jarvis (or any orchestrator) can call :func:`run_delegated_agent` to pass
a goal to a specialised managed agent and receive its final answer. The
delegation context (manager, engine, model, event bus) is registered
once at server startup via :func:`set_delegation_context`, so tools can
dispatch without having to plumb those objects through every call site.

Only agents whose config has ``visible_to_brain`` truthy (or whose
``delegation.visible_to_brain`` is truthy) are considered delegatable.
The primary Jarvis agent itself is excluded to prevent trivial cycles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openjarvis.agents.manager import AgentManager

logger = logging.getLogger("openjarvis.agents.delegation")

_JARVIS_AGENT_TYPE = "jarvis"


# ---------------------------------------------------------------------------
# Context registration
# ---------------------------------------------------------------------------


@dataclass
class DelegationContext:
    manager: AgentManager
    engine: Any
    model: str
    event_bus: Any = None
    trace_store: Any = None


_CTX: Optional[DelegationContext] = None


def set_delegation_context(
    manager: AgentManager,
    engine: Any,
    model: str,
    *,
    event_bus: Any = None,
    trace_store: Any = None,
) -> None:
    """Install the global delegation context. Call once at server startup."""
    global _CTX
    _CTX = DelegationContext(
        manager=manager,
        engine=engine,
        model=model,
        event_bus=event_bus,
        trace_store=trace_store,
    )
    logger.info(
        "Delegation context installed (manager=%s, model=%s)",
        type(manager).__name__,
        model,
    )


def get_delegation_context() -> Optional[DelegationContext]:
    return _CTX


def clear_delegation_context() -> None:
    """Test-only: reset the module-level context."""
    global _CTX
    _CTX = None


# ---------------------------------------------------------------------------
# Visibility helpers
# ---------------------------------------------------------------------------


def _is_visible_to_brain(agent: Dict[str, Any]) -> bool:
    cfg = agent.get("config") or {}
    if cfg.get("visible_to_brain") is True:
        return True
    delegation = cfg.get("delegation")
    if isinstance(delegation, dict) and delegation.get("visible_to_brain") is True:
        return True
    return False


def list_delegatable_agents(manager: AgentManager) -> List[Dict[str, Any]]:
    """Return a compact catalog of agents Jarvis may delegate to.

    The primary Jarvis row is excluded. Archived rows are excluded. Each
    entry is a small dict with just what the LLM needs to pick a target.
    """
    out: List[Dict[str, Any]] = []
    try:
        rows = manager.list_agents()
    except Exception:  # pragma: no cover - defensive
        logger.debug("list_agents() failed during delegation catalog", exc_info=True)
        return out

    for ag in rows:
        if ag.get("agent_type") == _JARVIS_AGENT_TYPE:
            continue
        if ag.get("status") == "archived":
            continue
        if not _is_visible_to_brain(ag):
            continue
        cfg = ag.get("config") or {}
        tags = cfg.get("delegation_tags")
        if not isinstance(tags, list):
            delegation = cfg.get("delegation") or {}
            tags = delegation.get("tags") if isinstance(delegation, dict) else None
            if not isinstance(tags, list):
                tags = []
        out.append(
            {
                "id": ag.get("id"),
                "name": ag.get("name"),
                "agent_type": ag.get("agent_type"),
                "description": cfg.get("description", ""),
                "tags": list(tags),
                "status": ag.get("status"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Synchronous delegated run
# ---------------------------------------------------------------------------


def _resolve_agent_by_ref(
    manager: AgentManager,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if agent_id:
        rec = manager.get_agent(agent_id)
        if rec is not None:
            return rec
    if agent_name:
        try:
            rows = manager.list_agents()
        except Exception:  # pragma: no cover
            return None
        lowered = agent_name.strip().lower()
        for ag in rows:
            if (ag.get("name") or "").strip().lower() == lowered:
                return ag
    return None


def _resolve_tool_instances(tool_names: List[str]) -> List[Any]:
    """Best-effort resolution of built-in tool names to instances.

    Unknown names are silently skipped. This mirrors the lenient
    behavior of ``_resolve_tool_specs`` in the managed-agent router.
    """
    from openjarvis.core.registry import ToolRegistry

    resolved: List[Any] = []
    for name in tool_names or []:
        if not isinstance(name, str) or not name:
            continue
        try:
            cls = ToolRegistry.get(name)
            if cls is None:
                continue
            resolved.append(cls())
        except Exception:
            logger.debug("Could not resolve tool %s for delegation", name, exc_info=True)
    return resolved


def run_delegated_agent(
    manager: AgentManager,
    engine: Any,
    model: str,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    goal: str,
    event_bus: Any = None,
) -> Dict[str, Any]:
    """Run a single turn of the target managed agent and return its answer.

    Returns a dict::

        {
            "success": bool,
            "agent_id": str | None,
            "agent_name": str | None,
            "content": str,       # final answer or error message
            "turns": int,
            "tool_calls": int,
            "error": str | None,
        }

    This never raises — errors are reported in the payload so the
    calling tool can forward them back to the orchestrator cleanly.
    """
    target = _resolve_agent_by_ref(
        manager, agent_id=agent_id, agent_name=agent_name
    )
    if target is None:
        ref = agent_id or agent_name or "<none>"
        return {
            "success": False,
            "agent_id": None,
            "agent_name": None,
            "content": f"No managed agent matched reference: {ref!r}",
            "turns": 0,
            "tool_calls": 0,
            "error": "not_found",
        }

    if target.get("agent_type") == _JARVIS_AGENT_TYPE:
        return {
            "success": False,
            "agent_id": target.get("id"),
            "agent_name": target.get("name"),
            "content": "Cannot delegate back to the primary Jarvis agent.",
            "turns": 0,
            "tool_calls": 0,
            "error": "self_delegation",
        }

    if not _is_visible_to_brain(target):
        return {
            "success": False,
            "agent_id": target.get("id"),
            "agent_name": target.get("name"),
            "content": (
                f"Agent {target.get('name')!r} is not marked visible_to_brain; "
                "it cannot be delegated to."
            ),
            "turns": 0,
            "tool_calls": 0,
            "error": "not_visible",
        }

    cfg = target.get("config") or {}
    agent_type = target.get("agent_type") or "simple"

    # Resolve the agent class. Fall back to a minimal wrapper if unknown.
    from openjarvis.core.registry import AgentRegistry

    try:
        agent_cls = AgentRegistry.get(agent_type)
    except Exception:
        agent_cls = None
    if agent_cls is None:
        return {
            "success": False,
            "agent_id": target.get("id"),
            "agent_name": target.get("name"),
            "content": f"Unknown agent_type: {agent_type!r}",
            "turns": 0,
            "tool_calls": 0,
            "error": "unknown_agent_type",
        }

    tools = _resolve_tool_instances(cfg.get("tools") or [])
    init_kwargs: Dict[str, Any] = {
        "engine": engine,
        "model": cfg.get("model") or model,
    }
    # Optional kwargs — pass only when the class accepts them.
    for key, src_key, default in (
        ("tools", None, tools),
        ("max_turns", "max_turns", cfg.get("max_turns", 4)),
        ("temperature", "temperature", cfg.get("temperature", 0.3)),
        ("max_tokens", "generation_max_tokens", cfg.get("generation_max_tokens", 1024)),
        ("system_prompt", "system_prompt", cfg.get("system_prompt") or None),
        ("bus", None, event_bus),
    ):
        if default is None:
            continue
        init_kwargs[key] = default

    try:
        agent = agent_cls(**{k: v for k, v in init_kwargs.items() if v is not None})
    except TypeError:
        # Retry with a minimal kwarg set if the target class has a stricter signature.
        try:
            agent = agent_cls(engine=engine, model=init_kwargs["model"])
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "success": False,
                "agent_id": target.get("id"),
                "agent_name": target.get("name"),
                "content": f"Failed to instantiate delegated agent: {exc}",
                "turns": 0,
                "tool_calls": 0,
                "error": "instantiation_failed",
            }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "success": False,
            "agent_id": target.get("id"),
            "agent_name": target.get("name"),
            "content": f"Failed to instantiate delegated agent: {exc}",
            "turns": 0,
            "tool_calls": 0,
            "error": "instantiation_failed",
        }

    try:
        result = agent.run(goal)
    except Exception as exc:
        logger.warning(
            "Delegated run to %s failed: %s", target.get("name"), exc, exc_info=True
        )
        return {
            "success": False,
            "agent_id": target.get("id"),
            "agent_name": target.get("name"),
            "content": f"Delegated agent raised: {exc}",
            "turns": 0,
            "tool_calls": 0,
            "error": "run_failed",
        }

    content = getattr(result, "content", None) or str(result)
    turns = int(getattr(result, "turns", 0) or 0)
    tool_results = getattr(result, "tool_results", None) or []
    return {
        "success": True,
        "agent_id": target.get("id"),
        "agent_name": target.get("name"),
        "content": content,
        "turns": turns,
        "tool_calls": len(tool_results),
        "error": None,
    }


__all__ = [
    "DelegationContext",
    "set_delegation_context",
    "get_delegation_context",
    "clear_delegation_context",
    "list_delegatable_agents",
    "run_delegated_agent",
]
