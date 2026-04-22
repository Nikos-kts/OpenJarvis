"""Jarvis skillset — discovers the full universe of available skills so
the HUD Capabilities surface can expose every shipped / user / overlay
skill for toggling.

Discovery order (first-seen-wins, same precedence as SkillManager):

1. Workspace ``./skills/`` (relative to the process CWD).
2. User skills dir — ``config.skills.skills_dir`` (default
   ``~/.openjarvis/skills/``).
3. Learning overlay — ``config.learning.skills.overlay_dir`` (default
   ``~/.openjarvis/learning/skills/``).
4. Bundled defaults shipped in ``openjarvis/skills/data/`` (20 curated
   starter skills such as ``web-summarize``, ``daily-digest``,
   ``code-lint`` …).  Surfacing these gives the user something useful
   to toggle on first launch even before they author their own.

This module only *discovers* manifests; it does not compile them into
SkillTool instances.  That remains the job of :class:`SkillManager`
inside the full System path.  The HUD only needs the metadata tuple.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.skills.loader import discover_skills
from openjarvis.skills.types import SkillManifest

logger = logging.getLogger(__name__)


def _bundled_skills_dir() -> Path:
    """Return the path to the shipped ``openjarvis/skills/data/`` dir."""
    # jarvis/skillset.py  ->  jarvis/  ->  openjarvis/
    # then sibling ``skills/data``.
    here = Path(__file__).resolve()
    return here.parent.parent / "skills" / "data"


def discover_jarvis_skills(
    config: Optional[Any] = None,
    *,
    include_bundled: bool = True,
) -> List[SkillManifest]:
    """Return every skill manifest visible to this process.

    Parameters
    ----------
    config:
        Full :class:`JarvisConfig`.  Reads
        ``config.skills.skills_dir`` and
        ``config.learning.skills.overlay_dir`` when provided.
    include_bundled:
        If *True* (default) the 20 curated skills shipped inside the
        package are appended after user/overlay locations, so a local
        override with the same name wins.

    Directories that do not exist are silently skipped; malformed
    manifests are logged at debug level and skipped.
    """
    paths: List[Path] = []

    # Workspace override (highest precedence)
    workspace = Path("skills")
    if workspace.exists():
        paths.append(workspace)

    # User skills directory
    if config is not None:
        user_dir = getattr(getattr(config, "skills", None), "skills_dir", None)
        if user_dir:
            paths.append(Path(str(user_dir)).expanduser())
        overlay_dir = getattr(
            getattr(getattr(config, "learning", None), "skills", None),
            "overlay_dir",
            None,
        )
        if overlay_dir:
            paths.append(Path(str(overlay_dir)).expanduser())

    # Bundled defaults
    if include_bundled:
        bundled = _bundled_skills_dir()
        if bundled.exists():
            paths.append(bundled)

    manifests: List[SkillManifest] = []
    seen: set[str] = set()
    for directory in paths:
        try:
            found = discover_skills(directory)
        except Exception:
            logger.debug("skill discovery failed for %s", directory, exc_info=True)
            continue
        for m in found:
            if not m.name or m.name in seen:
                continue
            seen.add(m.name)
            manifests.append(m)

    logger.info(
        "Jarvis skillset: discovered=%d from %d path(s)",
        len(manifests),
        len(paths),
    )
    return manifests


def manifest_to_api_dict(m: SkillManifest) -> Dict[str, Any]:
    """Project a :class:`SkillManifest` to the HUD wire format."""
    return {
        "name": m.name,
        "description": m.description or "",
        "version": m.version or "",
        "author": m.author or "",
        "tags": list(m.tags or []),
        "steps": len(m.steps or []),
        "user_invocable": bool(m.user_invocable),
    }


__all__ = ["discover_jarvis_skills", "manifest_to_api_dict"]
