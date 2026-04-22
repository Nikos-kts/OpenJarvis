"""Runtime configuration service.

Provides a single, thread-safe entry point for reading, serialising,
patching, and persisting :class:`~openjarvis.core.config.JarvisConfig`.

This is the backend primitive that powers the SettingsPage and the
``jarvis config set`` CLI.  Both surfaces must go through this service so
concurrent writes can't corrupt ``.openJarvis/config.toml``.

Key responsibilities
--------------------
* :meth:`ConfigService.dump` — dataclass tree → JSON-safe dict, with
  secret fields masked.
* :meth:`ConfigService.defaults` — defaults snapshot (JarvisConfig with
  fresh hardware detection, no TOML overlay).
* :meth:`ConfigService.schema` — JSON-Schema-ish description of the full
  config surface.  Used by the frontend to render forms dynamically.
* :meth:`ConfigService.apply_patch` — validates a ``{dotted_key: value}``
  mapping, coerces each value to the declared Python type, writes the
  changes back to the TOML file atomically (preserving comments via
  ``tomlkit``), invalidates the :func:`load_config` cache, and reloads.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import fields as dc_fields
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, get_args, get_origin

import tomlkit

from openjarvis.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    HardwareInfo,
    JarvisConfig,
    _SETTABLE_SECTIONS,
    apply_security_profile,
    detect_hardware,
    load_config,
    recommend_engine,
    validate_config_key,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secret / advanced field metadata
# ---------------------------------------------------------------------------

# Dotted keys (or ``section.*`` wildcards) that should be masked when dumped
# over HTTP.  These stay plaintext in ``config.toml`` (status quo), but the
# SettingsPage never sees the real values.
_SECRET_SUFFIXES: Tuple[str, ...] = (
    "api_key",
    "api_secret",
    "api_secret_key",
    "api_key_id",
    "secret",
    "secret_key",
    "password",
    "token",
    "bot_token",
    "auth_token",
    "access_token",
    "refresh_token",
    "app_secret",
    "webhook_secret",
    "verify_token",
    "client_secret",
    "signing_secret",
    "bluebubbles_password",
    "twilio_auth_token",
)

# Fields that require a server restart to take full effect (engine swap,
# listen host/port, middleware).  The :class:`SubsystemReloader` (Phase 3)
# owns the authoritative mapping; this list is consumed by ``schema()`` so
# the UI can flag them as "Restart required".
_RESTART_REQUIRED_PREFIXES: Tuple[str, ...] = (
    "engine.",
    "server.",
    "security.profile",
    "security.mode",
    "security.rate_limit_",
)

# Prefixes that should render collapsed under an "Advanced" drawer.
_ADVANCED_PREFIXES: Tuple[str, ...] = (
    "learning.",
    "optimize.",
    "a2a.",
    "operators.",
    "workflow.",
    "sandbox.",
    "agent_manager.",
    "memory_files.",
    "system_prompt.",
    "compression.",
    "skills.sources",
    "engine.vllm.",
    "engine.sglang.",
    "engine.llamacpp.",
    "engine.mlx.",
    "engine.exo.",
    "engine.nexa.",
    "engine.uzu.",
    "engine.apple_fm.",
    "engine.gemma_cpp.",
    "engine.lemonade.",
    "engine.lmstudio.",
)


MASKED_PLACEHOLDER = "__SECRET_SET__"
"""Sentinel returned by :meth:`dump` for secret fields that have a value.

If the frontend echoes this sentinel back in a ``PATCH`` request, the
service treats it as "no change" and preserves the stored value.  Any
other string (including the empty string) is written through verbatim.
"""


def _is_secret_key(dotted_key: str) -> bool:
    """Return True if the dotted key names a secret field."""
    tail = dotted_key.rsplit(".", 1)[-1].lower()
    return any(tail == s or tail.endswith("_" + s) for s in _SECRET_SUFFIXES) or any(
        tail == s for s in _SECRET_SUFFIXES
    )


# ---------------------------------------------------------------------------
# Dataclass -> dict
# ---------------------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    """Convert a value to a JSON-serialisable Python primitive."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if is_dataclass(value):
        return {
            f.name: _to_jsonable(getattr(value, f.name)) for f in dc_fields(value)
        }
    return str(value)


def _dump_dataclass(
    obj: Any,
    *,
    prefix: str,
    mask_secrets: bool,
) -> Dict[str, Any]:
    """Recursively dump a dataclass to a dict, optionally masking secrets."""
    result: Dict[str, Any] = {}
    for fld in dc_fields(obj):
        name = fld.name
        raw = getattr(obj, name)
        dotted = f"{prefix}.{name}" if prefix else name
        if is_dataclass(raw):
            result[name] = _dump_dataclass(
                raw, prefix=dotted, mask_secrets=mask_secrets
            )
        elif mask_secrets and _is_secret_key(dotted):
            result[name] = MASKED_PLACEHOLDER if raw else ""
        else:
            result[name] = _to_jsonable(raw)
    return result


# ---------------------------------------------------------------------------
# Type resolution / coercion
# ---------------------------------------------------------------------------


def _resolve_type(fld_type: Any) -> type:
    """Resolve a dataclass field's declared type string to a Python type."""
    if isinstance(fld_type, str):
        import openjarvis.core.config as _cfg_mod

        fld_type = eval(fld_type, vars(_cfg_mod))  # noqa: S307

    # Unwrap Optional[X] / Union[X, None]
    origin = get_origin(fld_type)
    if origin is not None:
        args = [a for a in get_args(fld_type) if a is not type(None)]
        if len(args) == 1:
            return _resolve_type(args[0])
        return fld_type  # list[...], dict[...], etc.
    return fld_type


def _coerce(value: Any, target: type) -> Any:
    """Coerce an incoming value to the declared dataclass field type."""
    if value is None:
        return None
    # Exact passthrough when already the right type (bool handled specially
    # because `bool` is a subclass of `int`).
    if target is bool:
        pass  # handled below
    elif target is Any:
        return value
    elif isinstance(target, type) and isinstance(value, target) and not isinstance(
        value, bool
    ):
        return value

    if target is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off", ""):
                return False
        raise ValueError(f"Cannot coerce {value!r} to bool")
    if target is int:
        return int(value)
    if target is float:
        return float(value)
    if target is str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)

    # Containers or unknown — best effort
    origin = get_origin(target)
    if origin in (list, tuple):
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
    return value


# ---------------------------------------------------------------------------
# JSON-schema generation
# ---------------------------------------------------------------------------


# Human-friendly titles per top-level section.  Anything not listed falls
# back to ``section.title().replace("_", " ")``.
_SECTION_TITLES: Dict[str, str] = {
    "engine": "Engine & Model",
    "intelligence": "Intelligence",
    "learning": "Learning",
    "tools": "Memory & Tools",
    "agent": "Agent",
    "server": "Server",
    "telemetry": "Telemetry",
    "traces": "Traces",
    "channel": "Channels",
    "security": "Security",
    "sandbox": "Sandbox",
    "scheduler": "Scheduler",
    "workflow": "Workflow",
    "sessions": "Sessions",
    "a2a": "Agent-to-Agent",
    "operators": "Operators",
    "speech": "Speech Settings",
    "optimize": "Optimize",
    "agent_manager": "Agent Manager",
    "memory_files": "Memory Files",
    "system_prompt": "System Prompt",
    "compression": "Compression",
    "skills": "Skills",
    "digest": "Morning Digest",
}

_TYPE_MAP: Dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _field_schema(
    cls: type,
    fld: Any,
    dotted: str,
    defaults_obj: Any,
) -> Dict[str, Any]:
    """Build a schema entry for a single dataclass field."""
    resolved = _resolve_type(fld.type)
    entry: Dict[str, Any] = {"dotted": dotted}

    if is_dataclass(resolved):
        nested_default = getattr(defaults_obj, fld.name, None)
        entry["type"] = "object"
        entry["properties"] = _dataclass_schema(
            resolved, prefix=dotted, defaults_obj=nested_default
        )
        return entry

    origin = get_origin(resolved)
    if origin in (list, tuple):
        entry["type"] = "array"
    else:
        entry["type"] = _TYPE_MAP.get(resolved, "string")

    default_val = _to_jsonable(getattr(defaults_obj, fld.name, None))
    entry["default"] = default_val

    if _is_secret_key(dotted):
        entry["secret"] = True
    if any(dotted.startswith(p) or dotted == p.rstrip(".") for p in _ADVANCED_PREFIXES):
        entry["advanced"] = True
    if any(
        dotted.startswith(p) or dotted == p.rstrip(".")
        for p in _RESTART_REQUIRED_PREFIXES
    ):
        entry["restart_required"] = True

    # Enum options declared via field(metadata={"enum": [...]}).
    enum_opts = fld.metadata.get("enum") if hasattr(fld, "metadata") else None
    if enum_opts:
        entry["enum"] = list(enum_opts)

    return entry


def _dataclass_schema(
    cls: type,
    *,
    prefix: str,
    defaults_obj: Any,
) -> Dict[str, Dict[str, Any]]:
    props: Dict[str, Dict[str, Any]] = {}
    for fld in dc_fields(cls):
        dotted = f"{prefix}.{fld.name}" if prefix else fld.name
        props[fld.name] = _field_schema(cls, fld, dotted, defaults_obj)
    return props


def build_schema(defaults: JarvisConfig) -> Dict[str, Any]:
    """Build a JSON-schema-ish description of the full JarvisConfig surface.

    Top-level sections are grouped into ``categories`` so the UI sidebar
    can render them in a stable order.  ``hardware`` is included as
    read-only.
    """
    sections: Dict[str, Dict[str, Any]] = {}
    for fld in dc_fields(JarvisConfig):
        name = fld.name
        resolved = _resolve_type(fld.type)
        if not is_dataclass(resolved):
            continue
        nested_default = getattr(defaults, name, None)
        sections[name] = {
            "title": _SECTION_TITLES.get(name, name.replace("_", " ").title()),
            "readonly": name == "hardware",
            "properties": _dataclass_schema(
                resolved, prefix=name, defaults_obj=nested_default
            ),
        }
    return {"sections": sections}


# ---------------------------------------------------------------------------
# TOML patching
# ---------------------------------------------------------------------------


def _read_toml_doc(path: Path) -> "tomlkit.TOMLDocument":
    if path.exists():
        return tomlkit.parse(path.read_text())
    return tomlkit.document()


def _set_nested(doc: Any, parts: List[str], value: Any) -> None:
    """Set a nested dotted key on a tomlkit document, creating tables."""
    current = doc
    for part in parts[:-1]:
        if part not in current:
            current.add(part, tomlkit.table())
        current = current[part]
    current[parts[-1]] = value


def _atomic_write(path: Path, text: str) -> None:
    """Atomic write: tempfile + fsync + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------


class PatchError(ValueError):
    """Raised when a PATCH request contains invalid keys or values."""

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__(f"Invalid config patch: {errors}")


class ConfigService:
    """Thread-safe accessor for the live :class:`JarvisConfig`.

    One instance is constructed at server startup and stored on
    ``app.state.config_service``.  The CLI's ``jarvis config set`` command
    also funnels writes through this class so the in-memory config, the
    TOML on disk, and subsystem reloaders stay in sync.
    """

    def __init__(
        self,
        *,
        config: Optional[JarvisConfig] = None,
        path: Optional[Path] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._path: Path = self._resolve_path(path)
        self._config: JarvisConfig = config if config is not None else load_config(
            self._path if self._path.exists() else None
        )

    # -- path helpers -----------------------------------------------------

    @staticmethod
    def _resolve_path(path: Optional[Path]) -> Path:
        if path is not None:
            return Path(path)
        env = os.environ.get("OPENJARVIS_CONFIG")
        if env:
            return Path(env).expanduser().resolve()
        return DEFAULT_CONFIG_PATH

    @property
    def path(self) -> Path:
        return self._path

    # -- read -------------------------------------------------------------

    def current(self) -> JarvisConfig:
        """Return the live in-memory config (caller must not mutate)."""
        return self._config

    def dump(self, *, mask_secrets: bool = True) -> Dict[str, Any]:
        """Dump the live config as a JSON-safe dict."""
        with self._lock:
            return _dump_dataclass(
                self._config, prefix="", mask_secrets=mask_secrets
            )

    def defaults(self) -> Dict[str, Any]:
        """Return a snapshot of defaults (hardware detected fresh)."""
        hw = detect_hardware()
        cfg = JarvisConfig(hardware=hw)
        cfg.engine.default = recommend_engine(hw)
        apply_security_profile(cfg.security, cfg.server)
        return _dump_dataclass(cfg, prefix="", mask_secrets=False)

    def schema(self) -> Dict[str, Any]:
        """Return the JSON-schema-ish description of the config surface."""
        hw = detect_hardware()
        cfg = JarvisConfig(hardware=hw)
        cfg.engine.default = recommend_engine(hw)
        return build_schema(cfg)

    def hardware(self) -> Dict[str, Any]:
        """Return the currently detected hardware info."""
        return _to_jsonable(self._config.hardware)

    # -- write ------------------------------------------------------------

    def apply_patch(
        self,
        patch: Dict[str, Any],
    ) -> Tuple[JarvisConfig, List[str]]:
        """Validate, persist, and reload a dotted-key patch.

        Parameters
        ----------
        patch:
            Mapping of dotted keys (e.g. ``"intelligence.temperature"``)
            to new values.

        Returns
        -------
        (new_config, changed_keys) where ``changed_keys`` contains only
        keys whose value actually differed from the stored one.
        """
        if not isinstance(patch, dict) or not patch:
            raise PatchError({"_root": "patch must be a non-empty object"})

        errors: Dict[str, str] = {}
        normalised: Dict[str, Any] = {}

        # Phase 1: validate + coerce every key before touching disk.
        for key, value in patch.items():
            if not isinstance(key, str) or not key:
                errors[str(key)] = "key must be a non-empty dotted string"
                continue
            # Preserve stored value for secrets echoed back as the sentinel.
            if value == MASKED_PLACEHOLDER and _is_secret_key(key):
                continue
            try:
                target_type = validate_config_key(key)
            except ValueError as exc:
                errors[key] = str(exc)
                continue
            try:
                normalised[key] = _coerce(value, _resolve_type(target_type))
            except (ValueError, TypeError) as exc:
                errors[key] = f"cannot coerce to {target_type}: {exc}"

        if errors:
            raise PatchError(errors)

        with self._lock:
            changed = self._write_and_reload(normalised)
            return self._config, changed

    def reload_from_disk(self) -> JarvisConfig:
        """Re-read the TOML file, bypassing the :func:`load_config` cache."""
        with self._lock:
            load_config.cache_clear()
            self._config = load_config(
                self._path if self._path.exists() else None
            )
            return self._config

    # -- internals --------------------------------------------------------

    def _write_and_reload(self, normalised: Dict[str, Any]) -> List[str]:
        """Merge ``normalised`` into the TOML doc, write atomically, reload."""
        doc = _read_toml_doc(self._path)

        # Build a lookup of current (pre-patch) values so we can report
        # which keys genuinely changed.
        changed: List[str] = []
        for dotted, new_value in normalised.items():
            parts = dotted.split(".")
            try:
                current_value = self._get_current(parts)
            except AttributeError:
                current_value = object()  # sentinel: treat as changed
            jsonable_new = _to_jsonable(new_value)
            if jsonable_new != _to_jsonable(current_value):
                changed.append(dotted)
            _set_nested(doc, parts, _toml_value(new_value))

        if not changed:
            # Nothing to persist.  Still re-run reload so callers get a
            # fresh JarvisConfig object.
            return []

        _atomic_write(self._path, tomlkit.dumps(doc))
        load_config.cache_clear()
        self._config = load_config(self._path)
        logger.info(
            "Applied config patch: %d key(s) changed: %s",
            len(changed),
            ", ".join(sorted(changed)),
        )
        return changed

    def _get_current(self, parts: List[str]) -> Any:
        current: Any = self._config
        for p in parts:
            current = getattr(current, p)
        return current


def _toml_value(value: Any) -> Any:
    """Normalise a Python value for storage in a tomlkit document."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


__all__ = [
    "ConfigService",
    "MASKED_PLACEHOLDER",
    "PatchError",
    "build_schema",
]
