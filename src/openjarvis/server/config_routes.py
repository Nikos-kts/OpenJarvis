"""HTTP endpoints for runtime configuration (SettingsPage backend).

Mounted at ``/v1/config``.  All reads / writes go through the shared
:class:`~openjarvis.core.config_service.ConfigService` instance stored on
``app.state.config_service``.

Endpoints
---------
* ``GET    /v1/config``           — current effective config (secrets masked).
* ``GET    /v1/config/defaults``  — defaults snapshot (secrets unmasked, since
  they are empty by definition).
* ``GET    /v1/config/schema``    — JSON-schema-ish surface used by the UI.
* ``GET    /v1/config/hardware``  — detected hardware info.
* ``PATCH  /v1/config``           — apply a dotted-key patch.
* ``POST   /v1/config/reload``    — re-read the TOML file from disk.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.core.config_service import ConfigService, PatchError

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/config", tags=["config"])


class PatchRequest(BaseModel):
    """Body for ``PATCH /v1/config``.

    Keys are dotted config paths (e.g. ``intelligence.temperature``) and
    values are the new values.  Secrets may be echoed back as the
    ``__SECRET_SET__`` sentinel to signal "no change".
    """

    patch: Dict[str, Any] = Field(default_factory=dict)


class PatchResponse(BaseModel):
    changed_keys: List[str]
    restart_required: bool
    restart_reasons: List[str]
    config: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_service(request: Request) -> ConfigService:
    svc = getattr(request.app.state, "config_service", None)
    if svc is None:
        # Lazy-init: allows the router to be mounted on apps that haven't
        # been through ``create_app`` (e.g. minimal test harnesses).
        svc = ConfigService()
        request.app.state.config_service = svc
    return svc


# Imported lazily to avoid a circular import at module load.
def _reload_subsystems(request: Request, changed_keys: List[str]) -> List[str]:
    reloader = getattr(request.app.state, "subsystem_reloader", None)
    if reloader is None:
        # No reloader wired up: treat every change as restart-required so the
        # UI still gives the user a clear signal.
        if changed_keys:
            return [f"{k}: subsystem reloader not registered" for k in changed_keys]
        return []
    try:
        return reloader.apply(changed_keys)  # type: ignore[no-any-return]
    except Exception as exc:
        logger.exception("Subsystem reload failed: %s", exc)
        return [f"reloader raised: {exc}"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def get_config(request: Request) -> Dict[str, Any]:
    svc = _get_service(request)
    return svc.dump(mask_secrets=True)


@router.get("/defaults")
async def get_defaults(request: Request) -> Dict[str, Any]:
    svc = _get_service(request)
    return svc.defaults()


@router.get("/schema")
async def get_schema(request: Request) -> Dict[str, Any]:
    svc = _get_service(request)
    return svc.schema()


@router.get("/hardware")
async def get_hardware(request: Request) -> Dict[str, Any]:
    svc = _get_service(request)
    return svc.hardware()


@router.patch("", response_model=PatchResponse)
async def patch_config(body: PatchRequest, request: Request) -> PatchResponse:
    svc = _get_service(request)
    try:
        _, changed = svc.apply_patch(body.patch)
    except PatchError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors})

    restart_reasons = _reload_subsystems(request, changed)
    return PatchResponse(
        changed_keys=sorted(changed),
        restart_required=bool(restart_reasons),
        restart_reasons=restart_reasons,
        config=svc.dump(mask_secrets=True),
    )


def _diff_dumps(
    before: Dict[str, Any], after: Dict[str, Any], prefix: str = ""
) -> List[str]:
    """Return dotted keys whose leaf values differ between two dumps."""
    changed: List[str] = []
    keys = set(before.keys()) | set(after.keys())
    for key in keys:
        dotted = f"{prefix}.{key}" if prefix else key
        b = before.get(key)
        a = after.get(key)
        if isinstance(b, dict) and isinstance(a, dict):
            changed.extend(_diff_dumps(b, a, dotted))
        elif b != a:
            changed.append(dotted)
    return changed


@router.post("/reload", response_model=PatchResponse)
async def reload_config(request: Request) -> PatchResponse:
    """Re-read ``config.toml`` from disk, hot-swap live config, surface reasons.

    Unlike PATCH, the user edited the file out-of-band, so we diff the old
    and new dumps to figure out what changed and then run the regular
    :class:`SubsystemReloader` pipeline.  The response mirrors the PATCH
    response shape so the UI can reuse the restart-banner wiring.
    """
    svc = _get_service(request)
    before = svc.dump(mask_secrets=True)
    svc.reload_from_disk()
    after = svc.dump(mask_secrets=True)
    changed = sorted(_diff_dumps(before, after))

    restart_reasons = _reload_subsystems(request, changed)
    return PatchResponse(
        changed_keys=changed,
        restart_required=bool(restart_reasons),
        restart_reasons=restart_reasons,
        config=after,
    )


__all__ = ["router"]
