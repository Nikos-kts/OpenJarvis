"""Jarvis toolset — enumerates and instantiates the full registered tool
universe so the HUD Capabilities surface can expose every tool that the
host process can actually construct.

The approach is deliberately defensive:

* Every class registered via ``@ToolRegistry.register(...)`` is
  considered a candidate.
* We try a sequence of constructor arg combinations — best-effort DI —
  so tools that take optional backends get them when available, but
  tools with purely positional arguments still work.
* Tools that fail to construct are skipped silently (logged at debug).
* Sensitive tools (shell access, patch application, arbitrary code
  execution, privileged agent lifecycle) are flagged so the UI can
  render a warning affordance.

This module is the *single place* where Jarvis's "all known tools"
list is composed; both the factory and tests consume it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


# Tools whose effects are hard to reverse or reach beyond the
# sandbox — surfaced with a warning icon in the HUD configure
# dialog, off by default unless explicitly enabled by the user.
SENSITIVE_TOOLS: FrozenSet[str] = frozenset(
    {
        "shell_exec",
        "apply_patch",
        "file_write",
        "code_interpreter",
        "code_interpreter_docker",
        "repl",
        "git_commit",
        "db_query",
        "agent_spawn",
        "agent_kill",
    }
)


# Human-readable rationale surfaced as the tooltip next to the
# warning icon.  Falls back to a generic message for any sensitive
# tool not explicitly listed here.
SENSITIVE_REASON: Dict[str, str] = {
    "shell_exec": "Executes arbitrary shell commands on the host.",
    "apply_patch": "Modifies files on the host filesystem via unified diffs.",
    "file_write": "Writes to the host filesystem.",
    "code_interpreter": "Runs arbitrary Python code in-process.",
    "code_interpreter_docker": "Runs arbitrary code in a Docker container.",
    "repl": "Keeps a stateful Python interpreter between calls.",
    "git_commit": "Creates commits in the current repository.",
    "db_query": "Runs arbitrary SQL against configured databases.",
    "agent_spawn": "Spawns new agents with privileged capabilities.",
    "agent_kill": "Terminates running agents.",
}


def sensitive_reason(name: str) -> str:
    """Return the tooltip shown alongside a tool's warning icon."""
    if name in SENSITIVE_REASON:
        return SENSITIVE_REASON[name]
    if name in SENSITIVE_TOOLS:
        return "Potentially destructive capability — review before enabling."
    return ""


def build_jarvis_tools(
    *,
    engine: Any = None,
    model: str = "",
    memory_backend: Any = None,
    channel_backend: Any = None,
    scheduler: Any = None,
    knowledge_store: Any = None,
    retriever: Any = None,
    only: Optional[Iterable[str]] = None,
    exclude: Iterable[str] = (),
) -> List[BaseTool]:
    """Instantiate every registered tool class that can be constructed
    with the provided runtime handles.

    Parameters
    ----------
    engine, model:
        Inference backend used by tools like ``llm`` and
        ``scan_chunks``.
    memory_backend:
        Concrete memory backend (``SqliteMemoryBackend`` etc.) used by
        storage and knowledge-graph tools.
    channel_backend:
        A :class:`BaseChannel`-compatible object (typically the
        server ``ChannelBridge``) used by the ``channel_*`` tools.
    scheduler:
        :class:`AgentScheduler` used by the ``schedule_task`` family;
        the scheduler tools read their backend from a class
        attribute, so we set it on the class once when provided.
    knowledge_store, retriever:
        Optional handles for ``knowledge_*`` / ``retrieval`` tools.
    only, exclude:
        Whitelist / blacklist of tool names.

    Returns
    -------
    list[BaseTool]
        Concrete instances, in registry insertion order.
    """
    # Side-effect: importing the tools package triggers the
    # ``@ToolRegistry.register(...)`` decorators so every tool module
    # is discoverable.  Scheduler tools live in a separate module.
    import openjarvis.tools  # noqa: F401

    # The tools package __init__ only imports a curated subset.
    # Pull in the rest so their decorators fire as well.  Any module
    # that raises at import (missing optional dep) is silently skipped.
    for _mod in (
        "openjarvis.tools.agent_tools",
        "openjarvis.tools.browser",
        "openjarvis.tools.browser_axtree",
        "openjarvis.tools.knowledge_search",
        "openjarvis.tools.knowledge_sql",
        "openjarvis.tools.knowledge_tools",
        "openjarvis.tools.scan_chunks",
        "openjarvis.tools.digest_collect",
        "openjarvis.tools.git_tool",
        "openjarvis.tools.image_tool",
        "openjarvis.tools.pdf_tool",
        "openjarvis.tools.memory_manage",
        "openjarvis.tools.skill_manage",
        "openjarvis.tools.user_profile_manage",
        "openjarvis.tools.apply_patch",
        "openjarvis.tools.file_write",
        "openjarvis.tools.db_query",
    ):
        try:
            __import__(_mod)
        except Exception:
            logger.debug("optional tool module %s not importable", _mod, exc_info=True)

    try:
        import openjarvis.scheduler.tools  # noqa: F401
    except Exception:
        logger.debug("scheduler tools module not importable", exc_info=True)

    only_set: Optional[Set[str]] = set(only) if only is not None else None
    exclude_set: Set[str] = set(exclude)

    # Install scheduler on the scheduler tool classes so all
    # instantiations share the reference.
    if scheduler is not None:
        try:
            from openjarvis.scheduler import tools as _sched_tools_mod

            for _attr in dir(_sched_tools_mod):
                _cls = getattr(_sched_tools_mod, _attr)
                if isinstance(_cls, type) and issubclass(_cls, BaseTool):
                    setattr(_cls, "_scheduler", scheduler)
        except Exception:
            logger.debug("failed to attach scheduler to tool classes", exc_info=True)

    built: List[BaseTool] = []
    for name in ToolRegistry.keys():
        if only_set is not None and name not in only_set:
            continue
        if name in exclude_set:
            continue
        try:
            cls = ToolRegistry.get(name)
        except Exception:
            continue
        if not (isinstance(cls, type) and issubclass(cls, BaseTool)):
            # Some entries may already be instances.
            if isinstance(cls, BaseTool):
                built.append(cls)
            continue
        instance = _try_instantiate(
            cls,
            name,
            engine=engine,
            model=model,
            memory_backend=memory_backend,
            channel_backend=channel_backend,
            knowledge_store=knowledge_store,
            retriever=retriever,
        )
        if instance is not None:
            built.append(instance)
    return built


def _try_instantiate(
    cls: type,
    name: str,
    *,
    engine: Any,
    model: str,
    memory_backend: Any,
    channel_backend: Any,
    knowledge_store: Any,
    retriever: Any,
) -> Optional[BaseTool]:
    """Try progressively simpler constructor arg sets until one works.

    The order matches the observed ``__init__`` signatures in
    ``src/openjarvis/tools``; most tools accept no arguments, so the
    empty-call fallback is always tried last.
    """
    attempts: List[Dict[str, Any]] = []

    # Tool-specific DI hints based on known signatures.
    if name in {"memory_store", "memory_retrieve", "memory_search", "memory_index"}:
        attempts.append({"backend": memory_backend})
    elif name in {"kg_add_entity", "kg_add_relation", "kg_query", "kg_neighbors"}:
        attempts.append({"backend": memory_backend})
    elif name == "retrieval":
        attempts.append({"backend": memory_backend})
    elif name in {"channel_send", "channel_list", "channel_status"}:
        attempts.append({"channel": channel_backend})
    elif name == "llm":
        attempts.append({"engine": engine, "model": model})
        attempts.append({"engine": engine})
    elif name == "scan_chunks":
        attempts.append(
            {"store": knowledge_store, "engine": engine, "model": model}
        )
    elif name == "knowledge_search":
        attempts.append({"store": knowledge_store, "retriever": retriever})
    elif name == "knowledge_sql":
        attempts.append({"store": knowledge_store})

    # Always fall back to the no-argument constructor — most tools
    # accept purely optional kwargs.
    attempts.append({})

    for kwargs in attempts:
        # Strip Nones so we don't pass ``backend=None`` when the tool
        # would otherwise have a sensible default.
        pruned = {k: v for k, v in kwargs.items() if v is not None}
        try:
            return cls(**pruned) if pruned else cls()
        except TypeError:
            continue
        except Exception:
            logger.debug("failed to build tool %s", name, exc_info=True)
            return None
    return None


__all__ = [
    "SENSITIVE_TOOLS",
    "SENSITIVE_REASON",
    "sensitive_reason",
    "build_jarvis_tools",
]
