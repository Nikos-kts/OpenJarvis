"""FastAPI router for ``/v1/jarvis/*``.

Endpoints
---------
``GET  /v1/jarvis/state``         — persona snapshot + metrics + sub-agents
``POST /v1/jarvis/reload``        — re-read SOUL/MEMORY/USER from disk
``GET  /v1/jarvis/delegations``   — recent delegation records
``POST /v1/jarvis/delegations/{id}/abort`` — mark a running delegation aborted
``GET  /v1/jarvis/events``        — tail of jarvis_events
``GET  /v1/jarvis/skills``        — all registered skills + active flag
``POST /v1/jarvis/skills/{name}/toggle`` — flip active state of a skill
``GET  /v1/jarvis/tools``         — all wired tools + active flag
``POST /v1/jarvis/tools/{name}/toggle`` — flip active state of a tool
``GET  /v1/jarvis/agents``        — delegatable sub-agents + allowlist flag
``POST /v1/jarvis/agents/{id}/toggle`` — flip delegation allowlist for an agent
``GET  /v1/jarvis/hud/prefs``     — HUD preferences (tab visibility)
``POST /v1/jarvis/hud/prefs``     — write HUD preferences
``POST /v1/jarvis/delegate``      — manual delegation (HUD quick action)
``GET  /v1/jarvis/stream``        — SSE live feed (bus events)

The router reads the :class:`JarvisAgent` from ``app.state.agent`` at
request time; it does not hold a reference, so hot-reloads (for
example when :class:`ConfigService` triggers a subsystem reload) work
transparently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/jarvis", tags=["jarvis"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_jarvis(request: Request) -> Any:
    """Return the active :class:`JarvisAgent`, or raise 503."""
    agent = getattr(request.app.state, "agent", None)
    # Duck-type check — Jarvis is identified by the presence of a
    # ``persona`` attribute and ``agent_id == "jarvis"``.
    if agent is None or getattr(agent, "agent_id", None) != "jarvis":
        raise HTTPException(
            status_code=503,
            detail="Jarvis is not the active primary agent.",
        )
    return agent


def _sub_agent_summaries(request: Request) -> list[dict]:
    mgr = getattr(request.app.state, "agent_manager", None)
    if mgr is None:
        return []
    try:
        agents = mgr.list_agents() or []
    except Exception:
        return []
    out: list[dict] = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        out.append(
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "agent_type": a.get("agent_type"),
                "status": a.get("status"),
                "model": (a.get("config") or {}).get("model"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# State / persona
# ---------------------------------------------------------------------------


@router.get("/state")
def get_state(request: Request) -> dict:
    """Return the current persona snapshot plus runtime metrics.

    This powers the HUD's main persona card and the top status bar.
    Cheap to call (SQLite single-row read + in-memory snapshot); the
    HUD polls it ~1 Hz.
    """
    jarvis = _get_jarvis(request)
    persona = jarvis.persona.snapshot()
    metrics = jarvis.store.get_metrics()
    session_start = getattr(request.app.state, "session_start", time.time())
    return {
        "agent_id": jarvis.agent_id,
        "model": jarvis._model,
        "persona": asdict(persona),
        "metrics": asdict(metrics),
        "uptime_seconds": max(0.0, time.time() - session_start),
        "tools": [t.spec.name for t in jarvis._tools],
        "sub_agents": _sub_agent_summaries(request),
        "active_skills": list(jarvis._active_skills),
        "delegation_enabled": any(
            t.spec.name == "delegate_to_subagent" for t in jarvis._tools
        ),
    }


@router.post("/reload")
def reload_persona(request: Request) -> dict:
    """Re-read SOUL/MEMORY/USER from disk and refresh the sub-agent list."""
    jarvis = _get_jarvis(request)
    jarvis.reload_persona()
    mgr = getattr(request.app.state, "agent_manager", None)
    if mgr is not None:
        try:
            names = [
                a.get("name", "")
                for a in (mgr.list_agents() or [])
                if isinstance(a, dict) and a.get("name")
            ]
            jarvis.set_sub_agents(names)
        except Exception:
            logger.debug("Failed to refresh sub-agent list", exc_info=True)
    jarvis.store.log_event("persona_reload", {})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Delegations / events
# ---------------------------------------------------------------------------


@router.get("/delegations")
def list_delegations(request: Request, limit: int = 20) -> dict:
    """Return the most recent delegation records.

    Used by the HUD's Delegation Timeline panel.
    """
    jarvis = _get_jarvis(request)
    limit = max(1, min(200, int(limit)))
    records = [asdict(r) for r in jarvis.store.recent_delegations(limit=limit)]
    return {"items": records, "count": len(records)}


@router.get("/events")
def list_events(request: Request, limit: int = 50) -> dict:
    """Return the tail of the compact event trace."""
    jarvis = _get_jarvis(request)
    limit = max(1, min(500, int(limit)))
    return {"items": jarvis.store.recent_events(limit=limit)}


# ---------------------------------------------------------------------------
# Skills (live enable / disable)
# ---------------------------------------------------------------------------


@router.get("/skills")
def list_skills(request: Request) -> dict:
    """Return all registered skills and which are currently active on Jarvis.

    The HUD uses this to render the Skills tab with per-skill toggles.
    ``items`` carries the full metadata (description, tags, version,
    author, step count) so the Configure Skills dialog can show rich
    rows for each shipped, user, or overlay skill.
    """
    jarvis = _get_jarvis(request)
    active = set(getattr(jarvis, "_active_skills", []) or [])
    raw = list(getattr(jarvis, "_all_skills", []) or [])

    # Fold in any active name that isn't in the discovered catalogue
    # so stale persisted entries still appear (and can be toggled off).
    seen = {item.get("name") for item in raw if isinstance(item, dict)}
    for name in sorted(active):
        if name not in seen:
            raw.append({"name": name})
            seen.add(name)

    items = []
    for meta in raw:
        if not isinstance(meta, dict) or not meta.get("name"):
            continue
        name = str(meta["name"])
        items.append(
            {
                "name": name,
                "description": str(meta.get("description") or ""),
                "version": str(meta.get("version") or ""),
                "author": str(meta.get("author") or ""),
                "tags": list(meta.get("tags") or []),
                "steps": int(meta.get("steps") or 0),
                "user_invocable": bool(meta.get("user_invocable", True)),
                "active": name in active,
            }
        )
    items.sort(key=lambda x: x["name"])
    return {"items": items, "active": sorted(active)}


@router.post("/skills/{name}/toggle")
def toggle_skill(request: Request, name: str) -> dict:
    """Enable or disable an active skill by name.

    Rebuilds the inner orchestrator on the next turn so the new
    persona prompt reflects the change immediately.
    """
    jarvis = _get_jarvis(request)
    active = list(getattr(jarvis, "_active_skills", []) or [])
    if name in active:
        active.remove(name)
        state = "disabled"
    else:
        active.append(name)
        state = "enabled"
    jarvis.set_active_skills(active)
    jarvis.store.log_event("jarvis_skill_toggled", {"name": name, "state": state})
    return {"ok": True, "name": name, "state": state, "active": active}


# ---------------------------------------------------------------------------
# Tools (live enable / disable, persisted)
# ---------------------------------------------------------------------------


@router.get("/tools")
def list_tools(request: Request) -> dict:
    """Return every tool Jarvis was wired with plus its active flag.

    The Capabilities Lab renders this as a toggleable list.  The
    universe is capped to tools that were actually instantiated at
    server start (``jarvis._all_tools``); registry entries that were
    never built — typically because they require specific construction
    arguments — are not exposed here.
    """
    jarvis = _get_jarvis(request)
    active = set(getattr(jarvis, "_active_tool_names", set()) or set())
    try:
        from openjarvis.jarvis.toolset import SENSITIVE_TOOLS, sensitive_reason
    except Exception:
        SENSITIVE_TOOLS = frozenset()  # type: ignore[assignment]

        def sensitive_reason(_name: str) -> str:  # type: ignore[no-redef]
            return ""

    items = []
    for t in getattr(jarvis, "_all_tools", []) or []:
        spec = t.spec
        items.append(
            {
                "name": spec.name,
                "description": spec.description,
                "category": getattr(spec, "category", "") or "",
                "latency_estimate": float(getattr(spec, "latency_estimate", 0.0) or 0.0),
                "active": spec.name in active,
                "sensitive": spec.name in SENSITIVE_TOOLS,
                "sensitive_reason": sensitive_reason(spec.name),
            }
        )
    items.sort(key=lambda x: (x["category"], x["name"]))
    return {"items": items, "active": sorted(active)}


@router.post("/tools/{name}/toggle")
def toggle_tool(request: Request, name: str) -> dict:
    """Flip the active flag of a tool and persist via the state store."""
    jarvis = _get_jarvis(request)
    known = {t.spec.name for t in getattr(jarvis, "_all_tools", []) or []}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    active = set(getattr(jarvis, "_active_tool_names", set()) or set())
    if name in active:
        active.discard(name)
        state = "disabled"
    else:
        active.add(name)
        state = "enabled"
    jarvis.set_active_tools(sorted(active))
    jarvis.store.log_event("jarvis_tool_toggled", {"name": name, "state": state})
    return {"ok": True, "name": name, "state": state, "active": sorted(active)}


# ---------------------------------------------------------------------------
# Sub-agent delegation allowlist
# ---------------------------------------------------------------------------


@router.get("/agents")
def list_delegatable_agents(request: Request) -> dict:
    """Return every managed sub-agent plus its delegation-allowlist flag.

    When the allowlist is ``None`` (first run / never configured) all
    known agents are considered active, matching the permissive
    default applied by :class:`DelegateToSubAgentTool`.
    """
    jarvis = _get_jarvis(request)
    agents = _sub_agent_summaries(request)
    allow = jarvis.store.get("active_agents", None)
    if isinstance(allow, list):
        wanted = {str(x) for x in allow}
        items = [
            {**a, "active": (a.get("id") in wanted) or (a.get("name") in wanted)}
            for a in agents
        ]
    else:
        items = [{**a, "active": True} for a in agents]
    active = sorted(x["name"] or x["id"] or "" for x in items if x.get("active"))
    return {"items": items, "active": active, "unrestricted": not isinstance(allow, list)}


@router.post("/agents/{agent_id}/toggle")
def toggle_delegatable_agent(request: Request, agent_id: str) -> dict:
    """Flip the delegation-allowlist flag for a managed sub-agent.

    On first toggle we *materialise* the allowlist to the current set
    of all known agents (minus the toggled one), so the previously-
    permissive default does not silently expand to new agents.
    """
    jarvis = _get_jarvis(request)
    agents = _sub_agent_summaries(request)
    known_ids = {a.get("id") for a in agents if a.get("id")}
    if agent_id not in known_ids:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")

    stored = jarvis.store.get("active_agents", None)
    if isinstance(stored, list):
        allow = {str(x) for x in stored}
    else:
        # Materialise: before any toggle every known agent was allowed.
        allow = {a.get("id") or "" for a in agents if a.get("id")}

    if agent_id in allow:
        allow.discard(agent_id)
        state = "disabled"
    else:
        allow.add(agent_id)
        state = "enabled"

    jarvis.set_active_agents(sorted(allow))
    jarvis.store.log_event("jarvis_agent_toggled", {"id": agent_id, "state": state})
    return {"ok": True, "id": agent_id, "state": state, "active": sorted(allow)}


# ---------------------------------------------------------------------------
# HUD preferences (tab visibility, etc.)
# ---------------------------------------------------------------------------

_DEFAULT_HUD_PREFS: dict = {
    "tabs_visible": {
        "capabilities": True,
        "delegation": True,
    },
    "sections_visible": {
        "tools": True,
        "skills": True,
        "agents": True,
    },
}


def _merge_hud_prefs(stored: Any) -> dict:
    """Deep-merge stored prefs over defaults, ignoring unknown keys."""
    out = {k: dict(v) for k, v in _DEFAULT_HUD_PREFS.items()}
    if not isinstance(stored, dict):
        return out
    for group, defaults in _DEFAULT_HUD_PREFS.items():
        got = stored.get(group)
        if isinstance(got, dict):
            for k in defaults:
                if k in got:
                    out[group][k] = bool(got[k])
    return out


@router.get("/hud/prefs")
def get_hud_prefs(request: Request) -> dict:
    jarvis = _get_jarvis(request)
    return _merge_hud_prefs(jarvis.store.get("hud_prefs", None))


@router.post("/hud/prefs")
def set_hud_prefs(request: Request, body: dict) -> dict:
    jarvis = _get_jarvis(request)
    merged = _merge_hud_prefs(body)
    jarvis.store.set("hud_prefs", merged)
    return merged


# ---------------------------------------------------------------------------
# Manual delegation (HUD Quick Actions)
# ---------------------------------------------------------------------------


@router.post("/delegate")
def delegate_manually(request: Request, body: dict) -> dict:
    """Direct invocation of the delegate-to-subagent tool.

    Bypasses Jarvis's own reasoning and hands a brief straight to a
    sub-agent.  Used by the HUD's "delegate" quick-action card so the
    operator can dispatch work without a chat roundtrip.

    Body schema: ``{"agent": "<id-or-name>", "brief": "...",
    "mode": "sync" | "async"}``.
    """
    jarvis = _get_jarvis(request)
    agent_name = str(body.get("agent", "")).strip()
    brief = str(body.get("brief", "")).strip()
    mode = str(body.get("mode", "async")).strip().lower()
    if not agent_name or not brief:
        raise HTTPException(status_code=400, detail="agent and brief are required")
    if mode not in ("sync", "async"):
        raise HTTPException(status_code=400, detail="mode must be 'sync' or 'async'")
    tool = next(
        (t for t in getattr(jarvis, "_tools", []) if getattr(t, "tool_id", None) == "delegate_to_subagent"),
        None,
    )
    if tool is None:
        raise HTTPException(status_code=409, detail="delegation is not enabled on this Jarvis")
    try:
        result = tool.execute(agent=agent_name, brief=brief, mode=mode)
    except Exception as exc:  # pragma: no cover - surface to client
        logger.exception("manual delegation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "ok": bool(getattr(result, "success", False)),
        "content": getattr(result, "content", ""),
        "metadata": getattr(result, "metadata", {}) or {},
    }


@router.post("/delegations/{delegation_id}/abort")
def abort_delegation(request: Request, delegation_id: str) -> dict:
    """Best-effort abort of a running delegation.

    Marks the record as ``aborted`` in the store and emits an event.
    The underlying sub-agent thread is not forcibly killed — cooperative
    cancellation is not yet supported by ``ToolUsingAgent.run``.  This
    endpoint therefore gives the HUD a way to *disown* a stuck
    delegation so the user isn't blocked waiting for it in the UI.
    """
    jarvis = _get_jarvis(request)
    records = jarvis.store.recent_delegations(limit=200)
    target = next((r for r in records if r.id == delegation_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="delegation not found")
    if target.status != "running":
        return {"ok": True, "status": target.status, "already_finished": True}
    jarvis.store.finish_delegation(
        delegation_id,
        status="aborted",
        error="aborted via HUD",
    )
    jarvis.store.log_event(
        "jarvis_delegation_aborted",
        {"id": delegation_id, "sub_agent": target.sub_agent},
    )
    return {"ok": True, "status": "aborted"}


# ---------------------------------------------------------------------------
# SSE stream — live HUD feed
# ---------------------------------------------------------------------------


# A conservative whitelist of event kinds we forward to the HUD.  The
# full telemetry bus is very chatty; the HUD only needs the signals
# that drive animations and activity widgets.
_FORWARDED_KINDS = frozenset(
    {
        "AGENT_TURN_START",
        "AGENT_TURN_END",
        "INFERENCE_START",
        "INFERENCE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_END",
        "AGENT_TICK_START",
        "AGENT_TICK_END",
    }
)


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of Jarvis-relevant bus events.

    The HUD opens this once on mount and listens for the lifetime of
    the page.  Each event is emitted as ``{"kind": ..., "data": ...}``.
    """
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="Event bus not available.")

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
    loop = asyncio.get_event_loop()

    def _forward(event: Any) -> None:
        kind = getattr(event, "type", None)
        kind_name = getattr(kind, "name", str(kind)) if kind is not None else ""
        if kind_name not in _FORWARDED_KINDS:
            return
        payload = {
            "kind": kind_name,
            "ts": getattr(event, "timestamp", time.time()),
            "data": getattr(event, "data", {}) or {},
        }
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except (RuntimeError, asyncio.QueueFull):
            pass  # drop on overflow or loop-closed

    # Subscribe to all tracked event types.
    from openjarvis.core.events import EventType

    subscribed: list[Any] = []
    for name in _FORWARDED_KINDS:
        et = getattr(EventType, name, None)
        if et is None:
            continue
        try:
            bus.subscribe(et, _forward)
            subscribed.append(et)
        except Exception:
            logger.debug("Failed to subscribe to %s", name, exc_info=True)

    async def _gen():
        try:
            # Initial hello so clients know the stream is alive
            yield f"data: {json.dumps({'kind': 'hello', 'ts': time.time()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keep-alive ping
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        finally:
            for et in subscribed:
                try:
                    bus.unsubscribe(et, _forward)
                except Exception:
                    pass

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
