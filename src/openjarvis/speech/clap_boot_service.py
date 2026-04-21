"""Clap-activated boot routine for wake and terminate gestures.

Runs as a background daemon thread. When two claps are detected via the
system microphone, the service foregrounds OpenJarvis and, once per active
wake cycle, sends a Jarvis boot message and executes the boot routine. When
three claps are detected, it performs a best-effort cleanup and terminates
the OpenJarvis desktop frontend.

Start via :func:`start_clap_boot_service` during server initialisation.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openjarvis.agents.executor import AgentExecutor
    from openjarvis.agents.manager import AgentManager
    from openjarvis.core.events import EventBus


# ── Boot-routine instruction injected as a pending message ──────────

BOOT_INSTRUCTION = """\
🟢 BOOT ROUTINE ACTIVATED ({timestamp}).

You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.
You were designed to be an indispensable personal AI assistant.
Your demeanor is that of a refined, loyal British butler: polite, \
concise, and quietly confident. You address the user as "sir" or "ma'am".
You are calm under pressure, occasionally dry-witted, and always efficient.

This activation was triggered by a double-clap wake signal.
Open with a short, polished wake-up response that:
- acknowledges activation,
- welcomes the user,
- gives a brief system-style status update,
- and offers assistance.

Perform the following startup sequence:

1. **System diagnostics** — Confirm all systems are online. State today's \
date, time, and a brief summary of available tools and integrations.
2. **Context recall** — Retrieve recent memory or session context. \
Briefly summarise anything relevant from previous sessions.
3. **Readiness** — Confirm you are standing by for instructions.

Keep the total response under 200 words. Maintain a composed, understated tone.\
"""

# ── Spoken briefing (Jarvis persona) ───────────────────────────────

_BRIEFING_TEMPLATE = (
    "Good {time_of_day}, sir. "
    "All systems are online and functioning within normal parameters. "
    "Today is {weekday}, the {day_ordinal} of {month}, {year}. "
    "We are in week {week_number}, with {days_remaining} days remaining in the year. "
    "Voice interface, agent pipeline, and all tool integrations are fully operational. "
    "At your service, sir."
)

_TTS_VOICE = "Enceladus"          # deep, authoritative Jarvis voice
_TTS_MODEL_DEFAULT = "gemini-2.5-flash-preview-tts"
_TTS_SAMPLE_RATE = 24_000         # Gemini TTS output rate

# Gemini models that support TTS via generateContent
# Ordered: free dedicated TTS first, then paid, then native audio (experimental for TTS)
TTS_MODEL_CHOICES: list[str] = [
    "gemini-2.5-flash-preview-tts",                     # FREE — stable dedicated TTS
    "gemini-3.1-flash-tts-preview",                      # FREE — newest dedicated TTS
    "gemini-2.5-pro-preview-tts",                        # PAID only — highest quality
    "gemini-2.5-flash-native-audio-preview-12-2025",     # FREE — Live API model (experimental for TTS)
]


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]}"


def _build_briefing_text() -> str:
    """Fill the briefing template with live date/time facts."""
    now = datetime.datetime.now()
    hour = now.hour
    if hour < 12:
        tod = "morning"
    elif hour < 17:
        tod = "afternoon"
    else:
        tod = "evening"

    day_of_year = now.timetuple().tm_yday
    year = now.year
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_remaining = (366 if leap else 365) - day_of_year

    return _BRIEFING_TEMPLATE.format(
        time_of_day=tod,
        weekday=now.strftime("%A"),
        day_ordinal=_ordinal(now.day),
        month=now.strftime("%B"),
        year=year,
        week_number=now.isocalendar()[1],
        days_remaining=days_remaining,
    )


class ClapBootService:
    """Bridges the :class:`ClapDetector` to the Jarvis managed-agent executor.

    The service supports two wake-up modes:

        * **clap** — listen for a double-clap to wake and triple-clap to quit.
    * **auto** — trigger the boot sequence automatically after a configurable
      delay once the backend has started.

    The active mode and auto-delay are persisted to
    ``~/.openjarvis/wake-mode.json`` so the setting survives restarts.

    1. Discovers the first managed agent of type ``jarvis``.
    2. On trigger, generates a spoken briefing via Gemini TTS and plays it
       through the system speakers.
    3. Sends the boot instruction as a pending message and triggers
       ``executor.execute_tick()``.
    """

    _PERSIST_PATH = os.path.expanduser("~/.openjarvis/wake-mode.json")

    def __init__(
        self,
        manager: AgentManager,
        executor: AgentExecutor,
        bus: EventBus | None = None,
        shutdown_callback: Callable[[], Any] | None = None,
    ) -> None:
        self._manager = manager
        self._executor = executor
        self._bus = bus
        self._jarvis_id: str | None = None
        self._running = False
        self._gemini_api_key: str = ""
        self._mode: str = "clap"          # "clap" | "auto" | "off"
        self._auto_delay: float = 5.0     # seconds after start before auto-boot
        self._tts_model: str = _TTS_MODEL_DEFAULT
        self._playback_speed: float = 1.0   # 0.5x – 2.0x
        self._auto_timer: threading.Timer | None = None
        self._detector: Any = None
        self._shutdown_callback = shutdown_callback
        self._state_lock = threading.Lock()
        self._bootstrapped_once = False
        self._shutdown_in_progress = False

    # ── lifecycle ───────────────────────────────────────────────

    def start(self, mode: str | None = None, auto_delay: float | None = None) -> None:
        """Resolve the Jarvis agent and activate the chosen wake mode.

        Parameters
        ----------
        mode:
            ``"clap"`` (default), ``"auto"``, or ``"off"``.
            If *None*, the persisted value from ``~/.openjarvis/wake-mode.json``
            is used.
        auto_delay:
            Seconds to wait before auto-boot.  Only relevant when *mode* is
            ``"auto"``.  If *None* the persisted value is used (default 5 s).
        """
        # Load persisted preferences first, then override with explicit args
        self._load_persisted()
        if mode is not None:
            self._mode = mode
        if auto_delay is not None:
            self._auto_delay = auto_delay

        self._jarvis_id = self._find_jarvis_agent()
        if self._jarvis_id is None:
            logger.warning(
                "ClapBootService: no managed agent of type 'jarvis' found — "
                "create one via POST /v1/managed-agents first."
            )
            return

        # Resolve Gemini API key for TTS
        self._gemini_api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        )
        if not self._gemini_api_key:
            logger.warning("ClapBootService: no GEMINI_API_KEY — speech playback disabled")

        self._activate_mode()
        self._running = True

    def _activate_mode(self) -> None:
        """Start clap detection or schedule auto-boot depending on mode."""
        # Tear down previous activations
        self._stop_clap()
        self._cancel_auto_timer()

        if self._mode == "clap":
            self._start_clap()
        elif self._mode == "auto":
            if self._has_bootstrapped_once():
                logger.info("Wake mode is 'auto' but boot routine already ran once — skipping re-bootstrap")
            else:
                self._schedule_auto_boot()
        else:
            logger.info("Wake mode is 'off' — Jarvis will not auto-wake")

    def _start_clap(self) -> None:
        """Start the clap listener for wake and terminate gestures."""
        try:
            from openjarvis.speech.clap_detector import ClapConfig, ClapDetector
        except RuntimeError:
            logger.warning(
                "ClapBootService: sounddevice/numpy not available. "
                "Install with: pip install 'openjarvis[speech-clap]'"
            )
            return
        cfg = ClapConfig(
            on_double_clap=self._on_double_clap,
            on_triple_clap=self._on_triple_clap,
        )
        self._detector = ClapDetector(cfg)
        self._detector.start()
        logger.info(
            "ClapBootService [clap] — listening for double-clap to wake and triple-clap to quit "
            "agent '%s' (%s)",
            "Jarvis",
            self._jarvis_id,
        )

    def _stop_clap(self) -> None:
        if self._detector is not None:
            try:
                self._detector.stop()
            except Exception:
                pass
            self._detector = None

    def _schedule_auto_boot(self) -> None:
        """Fire the boot sequence after *auto_delay* seconds."""
        logger.info(
            "ClapBootService [auto] — will wake Jarvis in %.1fs",
            self._auto_delay,
        )
        self._auto_timer = threading.Timer(
            self._auto_delay, self._auto_boot_callback,
        )
        self._auto_timer.daemon = True
        self._auto_timer.start()

    def _cancel_auto_timer(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.cancel()
            self._auto_timer = None

    def _auto_boot_callback(self) -> None:
        """Called by the auto-boot timer — triggers the same boot sequence."""
        logger.info(
            "=== AUTO WAKE-UP TRIGGERED (after %.1fs delay) — mode=%s, tts_model=%s ===",
            self._auto_delay, self._mode, self._tts_model,
        )
        self._on_double_clap()

    def stop(self) -> None:
        self._stop_clap()
        self._cancel_auto_timer()
        self._running = False
        logger.info("ClapBootService stopped")

    def set_shutdown_callback(self, callback: Callable[[], Any] | None) -> None:
        self._shutdown_callback = callback

    @property
    def running(self) -> bool:
        return self._running

    # ── mode management (used by API) ──────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def auto_delay(self) -> float:
        return self._auto_delay

    @property
    def tts_model(self) -> str:
        return self._tts_model

    @property
    def playback_speed(self) -> float:
        return self._playback_speed

    def set_mode(self, mode: str, auto_delay: float | None = None, tts_model: str | None = None, playback_speed: float | None = None) -> dict:
        """Switch wake mode at runtime and persist."""
        if mode not in ("clap", "auto", "off"):
            raise ValueError(f"Invalid wake mode: {mode!r}")
        self._mode = mode
        if mode == "off":
            self._reset_bootstrap_state()
        if auto_delay is not None:
            self._auto_delay = max(0.0, auto_delay)
        if tts_model is not None and tts_model in TTS_MODEL_CHOICES:
            self._tts_model = tts_model
        if playback_speed is not None:
            self._playback_speed = max(0.5, min(2.0, playback_speed))
        self._persist()
        if self._running:
            self._activate_mode()
        return self.get_status()

    def get_status(self) -> dict:
        return {
            "mode": self._mode,
            "auto_delay": self._auto_delay,
            "tts_model": self._tts_model,
            "tts_models": TTS_MODEL_CHOICES,
            "playback_speed": self._playback_speed,
            "running": self._running,
            "jarvis_agent_id": self._jarvis_id,
        }

    # ── persistence ────────────────────────────────────────────

    def _persist(self) -> None:
        """Write mode + delay to ``~/.openjarvis/wake-mode.json``."""
        import json as _json

        data = {"mode": self._mode, "auto_delay": self._auto_delay, "tts_model": self._tts_model, "playback_speed": self._playback_speed}
        try:
            os.makedirs(os.path.dirname(self._PERSIST_PATH), exist_ok=True)
            with open(self._PERSIST_PATH, "w") as fh:
                _json.dump(data, fh)
        except Exception:
            logger.debug("Failed to persist wake-mode", exc_info=True)

    def _load_persisted(self) -> None:
        """Read mode + delay from disk (if available)."""
        import json as _json

        try:
            with open(self._PERSIST_PATH) as fh:
                data = _json.load(fh)
            if data.get("mode") in ("clap", "auto", "off"):
                self._mode = data["mode"]
            if isinstance(data.get("auto_delay"), (int, float)):
                self._auto_delay = max(0.0, float(data["auto_delay"]))
            if data.get("tts_model") in TTS_MODEL_CHOICES:
                self._tts_model = data["tts_model"]
            if isinstance(data.get("playback_speed"), (int, float)):
                self._playback_speed = max(0.5, min(2.0, float(data["playback_speed"])))
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug("Failed to load wake-mode config", exc_info=True)

    # ── internal ────────────────────────────────────────────────

    def _find_jarvis_agent(self) -> str | None:
        """Return the ID of the first managed agent with agent_type='jarvis'."""
        for ag in self._manager.list_agents():
            if ag.get("agent_type") == "jarvis":
                return ag["id"]
        return None

    def _has_bootstrapped_once(self) -> bool:
        with self._state_lock:
            return self._bootstrapped_once

    def _mark_bootstrapped_once(self) -> bool:
        with self._state_lock:
            if self._bootstrapped_once or self._shutdown_in_progress:
                return False
            self._bootstrapped_once = True
            return True

    def _reset_bootstrap_state(self) -> None:
        with self._state_lock:
            self._bootstrapped_once = False
            self._shutdown_in_progress = False

    def _on_double_clap(self) -> None:
        """Callback fired by ClapDetector on a confirmed double-clap."""
        agent_id = self._jarvis_id
        if agent_id is None:
            return
        with self._state_lock:
            if self._shutdown_in_progress:
                logger.info("Wake trigger ignored — shutdown already in progress")
                return

        logger.info(
            "=== JARVIS WAKE-UP INITIATED — mode=%s, agent=%s, tts_model=%s ===",
            self._mode, agent_id, self._tts_model,
        )

        agent = self._manager.get_agent(agent_id)
        if agent is None:
            logger.error("Jarvis agent %s disappeared from DB", agent_id)
            return

        # Don't interrupt an agent that is actively running a tick right now.
        # A stale "running" status from a previous boot is reset to "idle".
        if agent.get("status") == "running":
            last_run = agent.get("last_run_at") or 0
            stale = (time.time() - last_run) > 120  # >2 min = stale
            if stale:
                logger.warning(
                    "Jarvis agent status is 'running' but last run was %.0fs ago "
                    "— resetting to 'idle'",
                    time.time() - last_run,
                )
                self._manager.update_agent(agent_id, status="idle")
            else:
                logger.info("Jarvis agent actively running — ignoring wake trigger")
                return

        should_bootstrap = self._mark_bootstrapped_once()
        if should_bootstrap:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            instruction = BOOT_INSTRUCTION.format(timestamp=timestamp)

            self._manager.send_message(
                agent_id,
                content=instruction,
            )
            logger.info("Boot instruction queued for Jarvis agent %s", agent_id)
        else:
            logger.info(
                "Jarvis already bootstrapped for the current wake cycle — foregrounding frontend only"
            )

        # Foreground the app every time, but only run the boot sequence once.
        threading.Thread(
            target=self._boot_sequence,
            args=(agent_id, should_bootstrap),
            daemon=True,
            name="jarvis-boot-sequence",
        ).start()

    def _on_triple_clap(self) -> None:
        with self._state_lock:
            if self._shutdown_in_progress:
                logger.info("Triple-clap ignored — shutdown already in progress")
                return
            self._shutdown_in_progress = True

        logger.info("=== JARVIS TERMINATION INITIATED — triple-clap detected ===")
        threading.Thread(
            target=self._shutdown_sequence,
            daemon=True,
            name="jarvis-shutdown-sequence",
        ).start()

    def _open_frontend(self) -> None:
        try:
            subprocess.Popen(["open", "-a", "OpenJarvis"])
            logger.info("Launched OpenJarvis.app")
        except Exception as exc:
            logger.warning("Could not launch OpenJarvis.app: %s", exc)

    def _boot_sequence(self, agent_id: str, should_bootstrap: bool) -> None:
        """Foreground the app and optionally run the Jarvis boot routine."""
        self._open_frontend()

        if not should_bootstrap:
            return

        logger.info("Boot sequence started — TTS briefing with model '%s'", self._tts_model)
        # 1. Generate and play spoken briefing
        self._speak_briefing()

        # 2. Execute the agent tick
        logger.info("Boot sequence — executing agent tick for %s", agent_id)
        self._execute_boot_tick(agent_id)

    def _speak_briefing(self) -> None:
        """Generate TTS audio via Gemini and play it through speakers."""
        if not self._gemini_api_key:
            logger.info("Skipping voice briefing — no GEMINI_API_KEY")
            return

        try:
            text = _build_briefing_text()
            logger.info("Generating Jarvis briefing TTS...")

            pcm_audio = asyncio.run(self._tts_generate(text))
            if not pcm_audio:
                logger.warning("TTS returned empty audio")
                return

            self._play_audio(pcm_audio)
        except Exception as exc:
            self._handle_tts_error(exc)

    def _handle_tts_error(self, exc: Exception) -> None:
        """Log a concise, actionable message for TTS failures."""
        msg = str(exc)
        exc_type = type(exc).__name__

        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            # Extract retry delay if present
            retry = ""
            if "retryDelay" in msg:
                import re
                m = re.search(r'"retryDelay":\s*"(\d+)s"', msg)
                if m:
                    retry = f" Retry in ~{m.group(1)}s."
            logger.warning(
                "TTS quota exceeded for model '%s' — free-tier daily limit "
                "reached.%s Briefing skipped; agent tick continues.",
                self._tts_model, retry,
            )
        elif "NOT_FOUND" in msg or "404" in msg:
            logger.warning(
                "TTS model '%s' not found — verify the model name is valid. "
                "Briefing skipped; agent tick continues.",
                self._tts_model,
            )
        elif "PERMISSION_DENIED" in msg or "403" in msg:
            logger.warning(
                "TTS permission denied for model '%s' — check your API key "
                "permissions. Briefing skipped; agent tick continues.",
                self._tts_model,
            )
        elif "INVALID_ARGUMENT" in msg or "400" in msg:
            logger.warning(
                "TTS invalid request for model '%s' — %s. "
                "Briefing skipped; agent tick continues.",
                self._tts_model, exc_type,
            )
        else:
            logger.warning(
                "Voice briefing failed (%s: %s) — continuing with agent tick.",
                exc_type, msg[:200],
            )

    async def _tts_generate(self, text: str) -> bytes:
        """Call Gemini TTS and return raw 24 kHz 16-bit mono PCM bytes."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._gemini_api_key)
        response = await client.aio.models.generate_content(
            model=self._tts_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=_TTS_VOICE,
                        )
                    )
                ),
            ),
        )
        audio_bytes = b""
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                audio_bytes += part.inline_data.data
        return audio_bytes

    def _play_audio(self, pcm_data: bytes) -> None:
        """Play raw 24 kHz 16-bit PCM through the default output device."""
        import numpy as np
        import sounddevice as sd

        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        effective_rate = int(_TTS_SAMPLE_RATE * self._playback_speed)
        logger.info(
            "Playing Jarvis briefing (%.1fs at %.1fx)...",
            len(samples) / effective_rate,
            self._playback_speed,
        )
        sd.play(samples, samplerate=effective_rate)
        sd.wait()  # block until playback finishes
        logger.info("Briefing playback complete")

    def _execute_boot_tick(self, agent_id: str) -> None:
        """Run one executor tick — same as POST /v1/managed-agents/{id}/run."""
        try:
            self._executor.execute_tick(agent_id)
            logger.info("Jarvis boot tick completed for %s", agent_id)
        except Exception:
            logger.exception("Jarvis boot tick failed for %s", agent_id)

    def _shutdown_sequence(self) -> None:
        self.stop()

        if self._shutdown_callback is not None:
            try:
                self._shutdown_callback()
            except Exception:
                logger.exception("ClapBootService shutdown callback failed")

        self._terminate_frontend()

    def _terminate_frontend(self) -> None:
        try:
            if shutil.which("osascript"):
                subprocess.Popen(
                    [
                        "osascript",
                        "-e",
                        'tell application "OpenJarvis" to quit',
                    ]
                )
                logger.info("Requested OpenJarvis.app termination via AppleScript")
                return
        except Exception as exc:
            logger.warning("Could not request OpenJarvis.app termination via AppleScript: %s", exc)

        try:
            subprocess.Popen(["pkill", "-f", "OpenJarvis.app"])
            logger.info("Requested OpenJarvis.app termination via pkill")
        except Exception as exc:
            logger.warning("Could not request OpenJarvis.app termination via pkill: %s", exc)
