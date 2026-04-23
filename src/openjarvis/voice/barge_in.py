"""Barge-in coordinator.

Detects when the user starts speaking while the assistant is playing back
audio (i.e. talking over it), then:
  1. Instructs the `AudioDaemonClient` to flush the playback queue.
  2. Signals the active `VoiceSession` to cancel the current provider stream.

The coordinator is a thin state machine that watches VAD events emitted by
the Rust daemon and the playback state maintained by the session layer.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Minimum time (seconds) after TTS starts before a VAD event can trigger
# barge-in. Prevents spurious interrupts from TTS audio leaking into the mic.
_ANTI_FEEDBACK_GRACE = 0.3


class BargeInCoordinator:
    """Monitors playback + VAD state and fires an interrupt callback."""

    def __init__(
        self,
        on_interrupt: Callable[[], None],
        anti_feedback_grace: float = _ANTI_FEEDBACK_GRACE,
    ) -> None:
        self._on_interrupt = on_interrupt
        self._grace = anti_feedback_grace
        self._playing = False
        self._tts_started_at: Optional[float] = None
        self._interrupted = False

    # ---- State setters (called by VoiceSession) -----------------------------

    def tts_started(self) -> None:
        """Signal that the assistant started speaking."""
        import time

        self._playing = True
        self._tts_started_at = time.monotonic()
        self._interrupted = False
        logger.debug("barge-in: TTS started")

    def tts_ended(self) -> None:
        """Signal that the assistant finished speaking."""
        self._playing = False
        self._tts_started_at = None
        logger.debug("barge-in: TTS ended")

    def reset(self) -> None:
        self._playing = False
        self._tts_started_at = None
        self._interrupted = False

    # ---- VAD event handler --------------------------------------------------

    def on_speech_start(self) -> bool:
        """Called when the daemon reports `speech_start`.

        Returns True if a barge-in was fired (caller should cancel the
        provider stream), False otherwise.
        """
        if not self._playing or self._interrupted:
            return False

        import time

        if self._tts_started_at is not None:
            elapsed = time.monotonic() - self._tts_started_at
            if elapsed < self._grace:
                logger.debug(
                    "barge-in suppressed (within %.0f ms grace period)",
                    self._grace * 1000,
                )
                return False

        logger.info("barge-in: user spoke during TTS — interrupting")
        self._interrupted = True
        self._playing = False
        try:
            self._on_interrupt()
        except Exception as exc:
            logger.warning("barge-in callback raised: %s", exc)
        return True
