"""Bootstrap helper: ensure the primary Jarvis managed agent exists.

The one managed-agents row with ``agent_type='jarvis'`` IS the Jarvis
orchestrator (the "Brain"). Chat, wake-word and realtime-voice pipelines
all resolve to it via :func:`find_jarvis_agent` or equivalent lookups.

This module creates that row on first startup, idempotently. First-run
defaults can be overridden by a TOML template at
``configs/openjarvis/jarvis_primary.toml`` (sibling of ``config.toml``)
or at ``~/.openjarvis/jarvis_primary.toml``. After bootstrap, edits go
to the database and the TOML is no longer consulted.

Controlled by ``config.agent_manager.auto_bootstrap_jarvis`` (default True).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:  # pragma: no cover - stdlib on Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from openjarvis.agents.manager import AgentManager

logger = logging.getLogger("openjarvis.agents.bootstrap")

_DEFAULT_JARVIS_NAME = "Jarvis"
_DEFAULT_JARVIS_TOOLS = [
    "web_search",
    "file_read",
    "calculator",
    "think",
]
_JARVIS_AGENT_TYPE = "jarvis"

# Candidate locations for the first-run TOML template, checked in order.
_TEMPLATE_CANDIDATES = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "openjarvis"
    / "jarvis_primary.toml",
    Path.home() / ".openjarvis" / "jarvis_primary.toml",
)


# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------


def _builtin_defaults(*, model: str, preferred_engine: str) -> Dict[str, Any]:
    """Return the built-in default config blob for the Jarvis agent."""
    return {
        "schedule_type": "manual",
        "schedule_value": "",
        "tools": list(_DEFAULT_JARVIS_TOOLS),
        "max_turns": 8,
        "temperature": 0.3,
        "generation_max_tokens": 2048,
        # system_prompt empty → runtime injects JARVIS_SYSTEM_PROMPT for
        # agent_type='jarvis'. Persisted edits win.
        "system_prompt": "",
        "model": model,
        "preferred_engine": preferred_engine,
        "description": (
            "Primary Jarvis orchestrator — acts as the central brain, "
            "delegating to other managed agents and tools."
        ),
        "persona": {
            "tone": "calm, refined, confident British butler",
            "verbosity": "balanced",
            "proactive_level": "medium",
            "wake_phrase": "At your service",
        },
        "intent": {
            "policy": "hybrid",
            "confidence_threshold": 0.55,
            "clarify_max_rounds": 1,
        },
        "voice": {
            "enabled": True,
            "realtime": True,
            "tts_voice": "Kore",
            "live_model": "gemini-live-2.5-flash-preview",
            "silence_seconds": 30,
        },
        "wake": {
            "enabled": True,
            "mode": "clap",
            "phrase": "jarvis",
        },
        "delegation": {
            "visible_to_brain": True,
            "tags": ["chat", "general"],
        },
        # Convenience flat mirrors for code that scans top-level keys.
        "visible_to_brain": True,
        "delegation_tags": ["chat", "general"],
    }


# ---------------------------------------------------------------------------
# TOML template loading
# ---------------------------------------------------------------------------


def _find_template() -> Optional[Path]:
    for candidate in _TEMPLATE_CANDIDATES:
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # pragma: no cover - defensive
            continue
    return None


def _load_template(path: Path) -> Dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge_template(
    base: Dict[str, Any], template: Dict[str, Any]
) -> Dict[str, Any]:
    """Overlay a parsed ``jarvis_primary.toml`` onto ``base`` (immutably)."""
    out: Dict[str, Any] = {}
    for k, v in base.items():
        if isinstance(v, dict):
            out[k] = dict(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v

    general = template.get("general") or {}
    if "description" in general:
        out["description"] = general["description"]

    runtime = template.get("runtime") or {}
    for key in ("max_turns", "temperature", "generation_max_tokens"):
        if key in runtime:
            out[key] = runtime[key]

    model = template.get("model") or {}
    if model.get("name"):
        out["model"] = model["name"]
    if model.get("preferred_engine"):
        out["preferred_engine"] = model["preferred_engine"]
    if model.get("provider"):
        out["model_provider"] = model["provider"]

    tools = template.get("tools") or {}
    if isinstance(tools.get("allow"), list):
        out["tools"] = list(tools["allow"])

    for section in ("persona", "intent", "voice", "wake"):
        if isinstance(template.get(section), dict):
            out[section] = {**out.get(section, {}), **template[section]}

    if isinstance(template.get("delegation"), dict):
        merged = {**out.get("delegation", {}), **template["delegation"]}
        out["delegation"] = merged
        if "visible_to_brain" in merged:
            out["visible_to_brain"] = bool(merged["visible_to_brain"])
        if isinstance(merged.get("tags"), list):
            out["delegation_tags"] = list(merged["tags"])

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def default_jarvis_config(
    *,
    model: str = "",
    preferred_engine: str = "",
    template_path: Optional[os.PathLike] = None,
) -> Dict[str, Any]:
    """Return the default managed-agent config blob for Jarvis.

    If a ``jarvis_primary.toml`` template is found (or ``template_path`` is
    passed), it overlays the built-in defaults. Parse errors fall back to
    the built-ins with a warning.
    """
    base = _builtin_defaults(model=model, preferred_engine=preferred_engine)

    path = Path(template_path) if template_path else _find_template()
    if path is None:
        return base
    try:
        template = _load_template(path)
    except Exception as exc:
        logger.warning(
            "Failed to parse %s: %s — falling back to built-ins", path, exc
        )
        return base
    merged = _merge_template(base, template)
    logger.info("Loaded Jarvis first-run defaults from %s", path)
    return merged


def find_jarvis_agent(manager: AgentManager) -> Optional[Dict[str, Any]]:
    """Return the first non-archived agent with agent_type='jarvis', or None."""
    try:
        for ag in manager.list_agents():
            if (
                ag.get("agent_type") == _JARVIS_AGENT_TYPE
                and ag.get("status") != "archived"
            ):
                return ag
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "list_agents() failed while looking for jarvis agent", exc_info=True
        )
    return None


def ensure_default_jarvis_agent(
    manager: AgentManager,
    *,
    name: str = _DEFAULT_JARVIS_NAME,
    model: str = "",
    preferred_engine: str = "",
    template_path: Optional[os.PathLike] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Return the managed Jarvis agent, creating one if none exists.

    Returns ``(agent, created)`` where ``created`` is True iff a new row
    was inserted.
    """
    existing = find_jarvis_agent(manager)
    if existing is not None:
        return existing, False

    cfg = default_jarvis_config(
        model=model,
        preferred_engine=preferred_engine,
        template_path=template_path,
    )
    agent = manager.create_agent(
        name=name,
        agent_type=_JARVIS_AGENT_TYPE,
        config=cfg,
    )
    logger.info(
        "Bootstrapped default Jarvis managed agent id=%s name=%s",
        agent.get("id"),
        name,
    )
    return agent, True


__all__ = [
    "default_jarvis_config",
    "find_jarvis_agent",
    "ensure_default_jarvis_agent",
]
