"""Factory — build the full :class:`JarvisAgent` from config.

Centralises the assembly so both the HTTP server entry
(``cli/serve.py``) and any future entry points (desktop bridge, tests)
can build the primary agent with one call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.jarvis.agent import JarvisAgent
from openjarvis.jarvis.delegation import build_delegate_tool
from openjarvis.jarvis.persona import JarvisPersona
from openjarvis.jarvis.state_store import JarvisStateStore
from openjarvis.jarvis.toolset import SENSITIVE_TOOLS, build_jarvis_tools
from openjarvis.jarvis.skillset import discover_jarvis_skills, manifest_to_api_dict
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


def build_jarvis_agent(
    config: JarvisConfig,
    *,
    engine: InferenceEngine,
    model: str,
    bus: Optional[EventBus] = None,
    core_tools: Optional[List[BaseTool]] = None,
    agent_manager: Optional[Any] = None,
    system: Optional[Any] = None,
    active_skills: Optional[List[str]] = None,
    memory_backend: Optional[Any] = None,
    channel_backend: Optional[Any] = None,
    scheduler: Optional[Any] = None,
    knowledge_store: Optional[Any] = None,
    retriever: Optional[Any] = None,
) -> Optional[JarvisAgent]:
    """Build a :class:`JarvisAgent` or return ``None`` if disabled.

    Parameters
    ----------
    config:
        Full :class:`JarvisConfig`.  Reads ``config.jarvis`` and
        ``config.memory_files`` and ``config.system_prompt``.
    engine, model:
        Inference backend.  ``config.jarvis.model`` overrides *model*
        when non-empty.
    bus:
        Event bus to publish Jarvis events to (HUD SSE subscribes here).
    core_tools:
        The "always-on" toolset that previously shipped with this
        deployment.  Used both as a bootstrap active-set when no user
        preference is stored *and* to compose the universe together
        with every other registered tool that can be constructed from
        the supplied runtime handles.
    agent_manager, system:
        Used to build the delegation tool.  Pass ``None`` to disable
        delegation (useful for unit tests).
    active_skills:
        Names of currently enabled procedural skills, rendered into
        the system prompt.
    memory_backend, channel_backend, scheduler, knowledge_store,
    retriever:
        Optional runtime handles injected into tools that need them.
        Missing handles silently skip the affected tool.
    """
    jc = config.jarvis
    if not jc.enabled:
        logger.info("Jarvis disabled (config.jarvis.enabled=false)")
        return None

    # Persona files + caps
    persona = JarvisPersona(
        name=jc.name,
        honorific=jc.honorific,
        voice_id=jc.voice_id,
        tts_backend=jc.tts_backend,
        soul_path=Path(config.memory_files.soul_path),
        memory_path=Path(config.memory_files.memory_path),
        user_path=Path(config.memory_files.user_path),
        soul_max_chars=config.system_prompt.soul_max_chars,
        memory_max_chars=config.system_prompt.memory_max_chars,
        user_max_chars=config.system_prompt.user_max_chars,
    )

    # Separate SQLite DB for Jarvis (NOT agents.db)
    store = JarvisStateStore(db_path=jc.state_db_path)

    # Delegation tool (optional)
    delegate_tool = None
    sub_names: List[str] = []
    if jc.delegation_enabled and agent_manager is not None and system is not None:
        delegate_tool = build_delegate_tool(
            manager=agent_manager,
            system=system,
            store=store,
            bus=bus,
        )
        try:
            sub_names = [
                a.get("name", "")
                for a in (agent_manager.list_agents() or [])
                if isinstance(a, dict) and a.get("name")
            ]
        except Exception:
            sub_names = []

    effective_model = jc.model or model

    # Full tool universe: start with the previously-wired *core_tools*
    # (they may be pre-configured with credentials or sandboxed paths
    # that the builder cannot reproduce) and add every other tool the
    # registry exposes that we can instantiate from runtime handles.
    core_names = {t.spec.name for t in (core_tools or [])}
    extra_tools = build_jarvis_tools(
        engine=engine,
        model=effective_model,
        memory_backend=memory_backend,
        channel_backend=channel_backend,
        scheduler=scheduler,
        knowledge_store=knowledge_store,
        retriever=retriever,
        exclude=core_names,
    )
    all_tools: List[BaseTool] = list(core_tools or []) + extra_tools
    logger.info(
        "Jarvis toolset: core=%d extra=%d total=%d",
        len(core_tools or []),
        len(extra_tools),
        len(all_tools),
    )

    # Full skill catalogue — scans workspace ``./skills/``, the user
    # skills dir, the learning overlay, and the 20 bundled defaults
    # shipped in ``openjarvis/skills/data/``.  Surfaced via the HUD
    # ``Configure Skills`` dialog so users can toggle without needing
    # to hand-edit config or drop files on disk first.
    try:
        manifests = discover_jarvis_skills(config)
    except Exception:
        logger.debug("skill discovery failed", exc_info=True)
        manifests = []
    all_skills_meta = [manifest_to_api_dict(m) for m in manifests]
    logger.info("Jarvis skillset: skills=%d", len(all_skills_meta))

    jarvis = JarvisAgent(
        engine,
        effective_model,
        persona=persona,
        store=store,
        tools=all_tools,
        bus=bus,
        max_turns=jc.max_turns,
        temperature=jc.temperature,
        max_tokens=jc.max_tokens,
        delegate_tool=delegate_tool,
        sub_agent_names=sub_names,
        active_skills=active_skills,
        default_active_tool_names=list(core_names),
        sensitive_tool_names=SENSITIVE_TOOLS,
        all_skills=all_skills_meta,
    )
    logger.info(
        "Built Jarvis: model=%s tools=%d (active=%d) sub_agents=%d delegation=%s",
        effective_model,
        len(jarvis._all_tools),
        len(jarvis._tools),
        len(sub_names),
        "on" if delegate_tool is not None else "off",
    )
    return jarvis
