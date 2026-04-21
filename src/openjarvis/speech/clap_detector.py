"""Clap detector — listens to the system microphone for wake and quit patterns.

Uses ``sounddevice`` for microphone capture and a simple amplitude-spike
algorithm to detect double-clap and triple-clap sequences within a
configurable time window.

Install the optional extra::

    pip install 'openjarvis[speech-clap]'
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

_sd: Any = None
_np: Any = None
_AVAILABLE = False

try:
    import numpy as _np_mod  # type: ignore[assignment]
    import sounddevice as _sd_mod  # type: ignore[assignment]

    _sd = _sd_mod
    _np = _np_mod
    _AVAILABLE = True
except ImportError:
    pass


@dataclass(slots=True)
class ClapConfig:
    """Tunable parameters for clap-sequence detection."""

    # ── Audio capture ──
    sample_rate: int = 44_100
    block_size: int = 1024          # samples per callback (~23 ms at 44.1 kHz)
    channels: int = 1

    # ── Spike detection ──
    rms_threshold: float = 0.06     # normalised RMS (0–1) to qualify as a clap
    peak_threshold: float = 0.12    # normalised peak amplitude for a clap

    # ── Clap timing ──
    min_gap: float = 0.08           # min seconds between two claps
    max_gap: float = 0.45           # max seconds between two claps
    cooldown: float = 2.0           # seconds to ignore after a confirmed trigger

    # ── Callbacks ──
    on_double_clap: Callable[[], Any] | None = None
    on_triple_clap: Callable[[], Any] | None = None


class ClapDetector:
    """Background microphone listener that fires callbacks on clap sequences.

    Usage::

        detector = ClapDetector(
            config=ClapConfig(
                on_double_clap=my_wake_callback,
                on_triple_clap=my_quit_callback,
            )
        )
        detector.start()   # non-blocking — daemon thread
        ...
        detector.stop()
    """

    def __init__(self, config: ClapConfig | None = None) -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "sounddevice / numpy not installed. "
                "Install with: pip install 'openjarvis[speech-clap]'"
            )
        self._cfg = config or ClapConfig()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # state for spike tracking
        self._last_clap_time: float = 0.0
        self._sequence_started_at: float = 0.0
        self._sequence_count: int = 0
        self._last_trigger_time: float = 0.0
        self._pending_double_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ── public API ──────────────────────────────────────────────

    def start(self) -> None:
        """Start listening on a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="jarvis-clap-detector",
        )
        self._thread.start()
        logger.info(
            "ClapDetector started (rms=%.2f, peak=%.2f, gap=%.2f–%.2fs)",
            self._cfg.rms_threshold,
            self._cfg.peak_threshold,
            self._cfg.min_gap,
            self._cfg.max_gap,
        )

    def stop(self) -> None:
        """Signal the listener to stop and wait for the thread."""
        self._stop_event.set()
        with self._lock:
            self._cancel_pending_double_locked()
            self._reset_sequence_locked()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("ClapDetector stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @staticmethod
    def available() -> bool:
        return _AVAILABLE

    # ── internal ────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Open an InputStream and process audio blocks until stopped."""
        try:
            stream = _sd.InputStream(
                samplerate=self._cfg.sample_rate,
                blocksize=self._cfg.block_size,
                channels=self._cfg.channels,
                dtype="float32",
            )
            stream.start()
            logger.info("Microphone stream opened for clap detection")
        except Exception:
            logger.exception("Failed to open microphone for clap detection")
            return

        try:
            while not self._stop_event.is_set():
                data, overflowed = stream.read(self._cfg.block_size)
                if overflowed:
                    continue
                self._process_block(data)
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("ClapDetector error in listen loop")
        finally:
            stream.stop()
            stream.close()
            logger.info("Microphone stream closed")

    def _process_block(self, data: Any) -> None:
        """Analyse a single audio block for a clap-like spike."""
        mono = data[:, 0] if data.ndim > 1 else data
        rms = float(_np.sqrt(_np.mean(mono ** 2)))
        peak = float(_np.max(_np.abs(mono)))

        # Log any audio above ambient floor so users can calibrate thresholds
        if rms > 0.01 or peak > 0.02:
            logger.debug("audio  rms=%.4f  peak=%.4f", rms, peak)

        if rms < self._cfg.rms_threshold or peak < self._cfg.peak_threshold:
            return

        now = time.monotonic()
        logger.debug(
            "spike! rms=%.4f  peak=%.4f  (thresholds rms>=%.2f peak>=%.2f)",
            rms, peak, self._cfg.rms_threshold, self._cfg.peak_threshold,
        )

        self._register_clap(now, rms=rms, peak=peak)

    def _register_clap(
        self,
        now: float,
        *,
        rms: float | None = None,
        peak: float | None = None,
    ) -> None:
        """Record a clap timestamp and dispatch double/triple callbacks."""
        trigger: str | None = None
        gap: float | None = None

        with self._lock:
            if now - self._last_trigger_time < self._cfg.cooldown:
                remaining = self._cfg.cooldown - (now - self._last_trigger_time)
                logger.debug("spike ignored — cooldown active (%.2fs left)", remaining)
                return

            if self._last_clap_time <= 0.0:
                logger.debug("first clap registered")
                self._sequence_started_at = now
                self._last_clap_time = now
                self._sequence_count = 1
                return

            gap = now - self._last_clap_time
            if gap < self._cfg.min_gap:
                logger.debug("spike ignored — gap %.3fs below min_gap %.3fs", gap, self._cfg.min_gap)
                return

            if gap > self._cfg.max_gap:
                logger.debug("gap out of range (%.3fs) — resetting first clap", gap)
                self._cancel_pending_double_locked()
                self._reset_sequence_locked()
                self._sequence_started_at = now
                self._last_clap_time = now
                self._sequence_count = 1
                return

            self._last_clap_time = now
            self._sequence_count += 1

            if self._sequence_count == 2:
                logger.debug("second clap registered — waiting for possible triple-clap")
                self._schedule_pending_double_locked()
                return

            if self._sequence_count >= 3:
                self._cancel_pending_double_locked()
                self._reset_sequence_locked()
                self._last_trigger_time = now
                trigger = "triple"

        if trigger == "triple":
            logger.info(
                "Triple-clap detected (rms=%s, peak=%s)",
                f"{rms:.3f}" if rms is not None else "n/a",
                f"{peak:.3f}" if peak is not None else "n/a",
            )
            self._fire_callback(self._cfg.on_triple_clap, name="triple")

    def _schedule_pending_double_locked(self) -> None:
        self._cancel_pending_double_locked()
        self._pending_double_timer = threading.Timer(
            self._cfg.max_gap,
            self._confirm_double_clap,
        )
        self._pending_double_timer.daemon = True
        self._pending_double_timer.start()

    def _confirm_double_clap(self) -> None:
        gap: float | None = None
        should_fire = False
        with self._lock:
            self._pending_double_timer = None
            if self._sequence_count != 2:
                return
            gap = self._last_clap_time - self._sequence_started_at
            self._reset_sequence_locked()
            self._last_trigger_time = time.monotonic()
            should_fire = True

        if should_fire:
            logger.info("Double-clap detected (gap=%.3fs)", gap or 0.0)
            self._fire_callback(self._cfg.on_double_clap, name="double")

    def _cancel_pending_double_locked(self) -> None:
        if self._pending_double_timer is not None:
            self._pending_double_timer.cancel()
            self._pending_double_timer = None

    def _reset_sequence_locked(self) -> None:
        self._sequence_started_at = 0.0
        self._last_clap_time = 0.0
        self._sequence_count = 0

    def _fire_callback(
        self,
        callback: Callable[[], Any] | None,
        *,
        name: str,
    ) -> None:
        if callback is None:
            return
        threading.Thread(
            target=self._safe_callback,
            args=(callback, name),
            daemon=True,
            name=f"jarvis-clap-{name}-callback",
        ).start()

    def _safe_callback(self, callback: Callable[[], Any], name: str) -> None:
        """Execute a clap callback with exception protection."""
        try:
            callback()
        except Exception:
            logger.exception("on_%s_clap callback failed", name)
