"""Auto-discover available speech-to-text backends."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.speech._stubs import SpeechBackend

logger = logging.getLogger(__name__)

# Priority order: local first, then cloud
DISCOVERY_ORDER = [
    "faster-whisper",
    "openai",
    "deepgram",
]


def _create_backend(
    key: str,
    config: "JarvisConfig",
) -> Optional["SpeechBackend"]:
    """Try to instantiate a speech backend by registry key."""
    from openjarvis.core.registry import SpeechRegistry

    if not SpeechRegistry.contains(key):
        logger.debug("Speech backend not registered: %s", key)
        return None

    try:
        backend_cls = SpeechRegistry.get(key)

        if key == "faster-whisper":
            return backend_cls(
                model_size=config.speech.model,
                device=config.speech.device,
                compute_type=config.speech.compute_type,
            )
        elif key == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                logger.debug(
                    "Skipping speech backend '%s': missing OPENAI_API_KEY",
                    key,
                )
                return None
            return backend_cls(api_key=api_key)
        elif key == "deepgram":
            api_key = os.environ.get("DEEPGRAM_API_KEY", "")
            if not api_key:
                logger.debug(
                    "Skipping speech backend '%s': missing DEEPGRAM_API_KEY",
                    key,
                )
                return None
            return backend_cls(api_key=api_key)
        else:
            return backend_cls()
    except Exception:
        logger.warning("Failed creating speech backend: %s", key, exc_info=True)
        return None


def get_speech_backend(config: "JarvisConfig") -> Optional["SpeechBackend"]:
    """Resolve the speech backend from config.

    If ``config.speech.backend`` is ``"auto"``, tries backends in
    priority order and returns the first healthy one.
    """
    # Trigger registration of built-in backends
    import openjarvis.speech  # noqa: F401

    backend_key = config.speech.backend

    if backend_key != "auto":
        backend = _create_backend(backend_key, config)
        if backend is not None:
            logger.debug("Selected configured speech backend: %s", backend_key)
        return backend

    # Auto-discovery: try each in priority order
    for key in DISCOVERY_ORDER:
        backend = _create_backend(key, config)
        if backend is not None:
            logger.debug("Auto-selected speech backend: %s", key)
            return backend

    logger.debug("No speech backend available after auto-discovery")
    return None
