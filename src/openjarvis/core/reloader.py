"""Subsystem reloader — applies config changes to a running server.

The hot-reload philosophy is intentionally conservative: only mutate
live subsystems for changes we've verified are safe.  For everything
else we return a "restart required" reason so the SettingsPage can show
a banner and `config.toml` stays the source of truth for the next boot.

How it works
------------
``SubsystemReloader`` is constructed once at server startup by
``create_app`` and stored on ``app.state.subsystem_reloader``.  The
``/v1/config`` PATCH endpoint invokes :meth:`SubsystemReloader.apply`
with the set of dotted keys that actually changed.

For each changed key, the reloader walks its handler registry
(longest-prefix match) and invokes the handler.  A handler may:

* Return ``None`` — change was hot-reloaded successfully.
* Return a non-empty string — change needs a restart; the string is
  surfaced to the user as the reason.

Keys with no matching handler default to "hot-reload safe (no action
required)" because request-time reads of ``app.state.config`` already
see the fresh value — this is true for anything whose only consumer
re-reads config on every request.

Registered handlers (initial set)
---------------------------------
* ``engine.*``              → restart required (engine swap mid-request is unsafe)
* ``server.host``           → restart required
* ``server.port``           → restart required
* ``server.workers``        → restart required
* ``server.cors_origins``   → restart required
* ``security.profile``      → restart required
* ``security.mode``         → restart required
* ``security.rate_limit_*`` → restart required (middleware is built once)

Anything else is hot-swapped by virtue of ``app.state.config`` being
replaced with the new :class:`JarvisConfig` instance before the
handlers run.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from fastapi import FastAPI

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventType

logger = logging.getLogger(__name__)


# A handler returns ``None`` on success or a human-readable restart reason.
ReloadHandler = Callable[[FastAPI, JarvisConfig, List[str]], Optional[str]]


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


def _restart_required(reason: str) -> ReloadHandler:
    def _handler(
        app: FastAPI, cfg: JarvisConfig, keys: List[str]
    ) -> Optional[str]:  # noqa: ARG001
        return reason

    return _handler


def _engine_handler(
    app: FastAPI, cfg: JarvisConfig, keys: List[str]
) -> Optional[str]:  # noqa: ARG001
    """Engine swaps mid-request are unsafe; require restart."""
    return "engine configuration changed — restart required"


def _server_handler(
    app: FastAPI, cfg: JarvisConfig, keys: List[str]
) -> Optional[str]:  # noqa: ARG001
    return "server host / port / middleware changed — restart required"


def _security_mode_handler(
    app: FastAPI, cfg: JarvisConfig, keys: List[str]
) -> Optional[str]:  # noqa: ARG001
    return (
        "security profile or rate-limit configuration changed — "
        "restart required"
    )


# ---------------------------------------------------------------------------
# Reloader
# ---------------------------------------------------------------------------


class SubsystemReloader:
    """Applies config changes to the live FastAPI app."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._handlers: Dict[str, ReloadHandler] = {}
        self._register_builtins()

    # -- registration ------------------------------------------------------

    def register(self, prefix: str, handler: ReloadHandler) -> None:
        """Register a handler for a dotted-key prefix.

        Prefix matching is exact or dotted-prefix: ``"engine"`` matches
        ``"engine.default"`` and ``"engine.ollama.host"``.  Longer
        prefixes win over shorter ones.
        """
        self._handlers[prefix] = handler

    def _register_builtins(self) -> None:
        self.register("engine", _engine_handler)
        self.register("server.host", _server_handler)
        self.register("server.port", _server_handler)
        self.register("server.workers", _server_handler)
        self.register("server.cors_origins", _server_handler)
        self.register("server.api_key", _server_handler)
        self.register("security.profile", _security_mode_handler)
        self.register("security.mode", _security_mode_handler)
        self.register("security.rate_limit_enabled", _security_mode_handler)
        self.register("security.rate_limit_rpm", _security_mode_handler)
        self.register("security.rate_limit_burst", _security_mode_handler)

    # -- apply -------------------------------------------------------------

    def apply(self, changed_keys: List[str]) -> List[str]:
        """Run reload handlers for ``changed_keys``.

        Returns a list of restart-required reasons (empty on full
        hot-reload success).
        """
        if not changed_keys:
            return []

        # Hot-swap the live config reference first — everything downstream
        # that reads ``app.state.config`` at request time will now see the
        # new values automatically.
        svc = getattr(self._app.state, "config_service", None)
        if svc is not None:
            self._app.state.config = svc.current()

        reasons: List[str] = []
        handled_keys: List[str] = []

        for key in changed_keys:
            handler = self._match(key)
            if handler is None:
                handled_keys.append(key)
                continue
            try:
                reason = handler(self._app, self._app.state.config, changed_keys)
            except Exception as exc:
                logger.exception("Reload handler failed for %s: %s", key, exc)
                reasons.append(f"{key}: handler error: {exc}")
                continue
            if reason:
                reasons.append(f"{key}: {reason}")
            else:
                handled_keys.append(key)

        # Emit CONFIG_UPDATED so learning / traces / any observer can react.
        bus = getattr(self._app.state, "bus", None)
        if bus is not None:
            try:
                bus.publish(
                    EventType.CONFIG_UPDATED,
                    {
                        "changed_keys": sorted(changed_keys),
                        "hot_reloaded": sorted(handled_keys),
                        "restart_required": bool(reasons),
                    },
                )
            except Exception:
                logger.exception("Failed to publish CONFIG_UPDATED event")

        logger.info(
            "Config reload: %d keys changed, %d hot-swapped, %d need restart",
            len(changed_keys),
            len(handled_keys),
            len(reasons),
        )
        # De-duplicate reasons while preserving order.
        seen = set()
        unique_reasons: List[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)
        return unique_reasons

    # -- internals ---------------------------------------------------------

    def _match(self, key: str) -> Optional[ReloadHandler]:
        """Longest-prefix match against registered handlers."""
        best_prefix = ""
        for prefix in self._handlers:
            if key == prefix or key.startswith(prefix + "."):
                if len(prefix) > len(best_prefix):
                    best_prefix = prefix
        return self._handlers.get(best_prefix) if best_prefix else None


__all__ = ["ReloadHandler", "SubsystemReloader"]
