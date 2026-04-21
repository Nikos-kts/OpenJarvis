"""FastAPI routes for the primary Jarvis managed agent.

These are thin, stable wrappers around the existing ``/v1/managed-agents``
endpoints, scoped to the single row with ``agent_type='jarvis'``. The
frontend can hit them without having to first resolve the jarvis agent
id, and external tooling gets a stable URL ("the primary Jarvis config")
regardless of what id the DB assigned.

Endpoints
---------
GET    /v1/jarvis/primary           → full agent record
GET    /v1/jarvis/primary/config    → just the config dict
PATCH  /v1/jarvis/primary/config    → partial deep-merge update of config
POST   /v1/jarvis/primary/reset     → overwrite config with first-run defaults
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    raise ImportError("fastapi and pydantic are required for server routes")

from openjarvis.agents.bootstrap import default_jarvis_config, find_jarvis_agent
from openjarvis.agents.manager import AgentManager

logger = logging.getLogger("openjarvis.server.jarvis_primary")


class JarvisPrimaryConfigPatch(BaseModel):
    config: Dict[str, Any]


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep-merged copy of ``base`` updated by ``patch``.

    Nested dicts are merged recursively; lists and scalars are replaced.
    """
    out = copy.deepcopy(base) if base else {}
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _require_primary(manager: AgentManager) -> Dict[str, Any]:
    agent = find_jarvis_agent(manager)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Primary Jarvis agent not found. Enable "
                "agent_manager.auto_bootstrap_jarvis or create a managed "
                "agent with agent_type='jarvis'."
            ),
        )
    return agent


def create_jarvis_primary_router(manager: AgentManager) -> "APIRouter":
    """Build the ``/v1/jarvis/primary`` router."""
    router = APIRouter(prefix="/v1/jarvis/primary", tags=["jarvis-primary"])

    @router.get("")
    async def get_primary() -> Dict[str, Any]:
        return _require_primary(manager)

    @router.get("/config")
    async def get_primary_config() -> Dict[str, Any]:
        agent = _require_primary(manager)
        return {
            "agent_id": agent["id"],
            "name": agent.get("name"),
            "config": agent.get("config") or {},
        }

    @router.patch("/config")
    async def patch_primary_config(req: JarvisPrimaryConfigPatch) -> Dict[str, Any]:
        agent = _require_primary(manager)
        current = agent.get("config") or {}
        merged = _deep_merge(current, req.config)
        updated = manager.update_agent(agent["id"], config=merged)
        return {
            "agent_id": agent["id"],
            "config": (updated or {}).get("config", merged),
        }

    @router.post("/reset")
    async def reset_primary_config(
        model: Optional[str] = None,
        preferred_engine: Optional[str] = None,
    ) -> Dict[str, Any]:
        agent = _require_primary(manager)
        current = agent.get("config") or {}
        # Inherit existing model/engine when caller doesn't override.
        effective_model = model if model is not None else current.get("model", "")
        effective_engine = (
            preferred_engine
            if preferred_engine is not None
            else current.get("preferred_engine", "")
        )
        fresh = default_jarvis_config(
            model=effective_model,
            preferred_engine=effective_engine,
        )
        updated = manager.update_agent(agent["id"], config=fresh)
        return {
            "agent_id": agent["id"],
            "config": (updated or {}).get("config", fresh),
        }

    return router


__all__ = ["create_jarvis_primary_router"]
