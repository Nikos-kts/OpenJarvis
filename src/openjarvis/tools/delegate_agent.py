"""Delegation tools for the primary Jarvis orchestrator.

Two registered tools:

* ``list_available_agents`` — returns a compact JSON catalog of managed
  agents that are marked ``visible_to_brain``. Jarvis calls this before
  choosing a delegation target.
* ``delegate_to_agent`` — runs a single turn of the target agent against
  a goal and returns its final answer. The target is resolved by id or
  name; the agent must be ``visible_to_brain`` and must not itself be
  the primary Jarvis agent (no self-delegation cycles).

Both tools rely on the module-level delegation context installed at
server startup via
:func:`openjarvis.agents.delegation.set_delegation_context`. When the
context is missing (e.g. during unit tests that don't boot the server),
the tools return a structured error payload rather than raising.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openjarvis.agents.delegation import (
    get_delegation_context,
    list_delegatable_agents,
    run_delegated_agent,
)
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _no_context_result(tool_name: str) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        content=json.dumps(
            {
                "success": False,
                "error": "no_delegation_context",
                "message": (
                    "Delegation context not initialised. This tool only works"
                    " inside a running OpenJarvis server."
                ),
            }
        ),
        success=False,
    )


@ToolRegistry.register("list_available_agents")
class ListAvailableAgentsTool(BaseTool):
    """Return the catalog of agents Jarvis may delegate to."""

    tool_id = "list_available_agents"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_available_agents",
            description=(
                "List the managed agents that Jarvis is allowed to delegate"
                " work to. Returns a JSON array of {id, name, agent_type,"
                " description, tags, status}. Call this before"
                " delegate_to_agent to know who is available."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="delegation",
            cost_estimate=0.0,
            latency_estimate=0.01,
        )

    def execute(self, **_: Any) -> ToolResult:
        ctx = get_delegation_context()
        if ctx is None:
            return _no_context_result("list_available_agents")
        try:
            catalog = list_delegatable_agents(ctx.manager)
        except Exception as exc:
            logger.warning("list_delegatable_agents failed: %s", exc, exc_info=True)
            return ToolResult(
                tool_name="list_available_agents",
                content=json.dumps(
                    {"success": False, "error": "list_failed", "message": str(exc)}
                ),
                success=False,
            )
        return ToolResult(
            tool_name="list_available_agents",
            content=json.dumps({"success": True, "agents": catalog}),
            success=True,
        )


@ToolRegistry.register("delegate_to_agent")
class DelegateToAgentTool(BaseTool):
    """Delegate a goal to another managed agent and return its answer."""

    tool_id = "delegate_to_agent"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="delegate_to_agent",
            description=(
                "Delegate a goal to another managed agent and receive its"
                " final answer synchronously. Either agent_id or"
                " agent_name must be provided. The target must be marked"
                " visible_to_brain. Use list_available_agents first to"
                " find candidates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UUID of the target managed agent.",
                    },
                    "agent_name": {
                        "type": "string",
                        "description": (
                            "Human-readable name of the target agent"
                            " (case-insensitive). Used only when"
                            " agent_id is omitted."
                        ),
                    },
                    "goal": {
                        "type": "string",
                        "description": (
                            "The task or question to hand off to the"
                            " target agent. Be specific and self-contained."
                        ),
                    },
                },
                "required": ["goal"],
            },
            category="delegation",
            cost_estimate=0.5,
            latency_estimate=5.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        ctx = get_delegation_context()
        if ctx is None:
            return _no_context_result("delegate_to_agent")

        goal = (params.get("goal") or "").strip()
        if not goal:
            return ToolResult(
                tool_name="delegate_to_agent",
                content=json.dumps(
                    {"success": False, "error": "missing_goal",
                     "message": "goal is required and must be non-empty."}
                ),
                success=False,
            )

        agent_id = params.get("agent_id") or None
        agent_name = params.get("agent_name") or None
        if not agent_id and not agent_name:
            return ToolResult(
                tool_name="delegate_to_agent",
                content=json.dumps(
                    {"success": False, "error": "missing_target",
                     "message": "Either agent_id or agent_name must be provided."}
                ),
                success=False,
            )

        payload = run_delegated_agent(
            ctx.manager,
            ctx.engine,
            ctx.model,
            agent_id=agent_id,
            agent_name=agent_name,
            goal=goal,
            event_bus=ctx.event_bus,
        )
        return ToolResult(
            tool_name="delegate_to_agent",
            content=json.dumps(payload),
            success=bool(payload.get("success")),
        )


__all__ = ["ListAvailableAgentsTool", "DelegateToAgentTool"]
