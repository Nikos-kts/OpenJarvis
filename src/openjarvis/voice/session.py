"""VoiceSession — provider router with failover.

Ties together:
- `AudioDaemonClient` (Rust daemon WS)
- A provider chain (Gemini → Deepgram → Local)
- `ConversationContext` (survives provider swap)
- `BargeInCoordinator`

The session runs as a long-lived asyncio task. Callers communicate via:
- `send_audio(pcm_bytes)` — push PCM16 from a client (e.g. WebSocket relay,
  though normally the daemon feeds the provider directly).
- `events()` — async generator of session-level `SessionEvent` dicts that
  the React UI subscribes to via `/v1/voice/events`.
- `interrupt()` — force a barge-in programmatically.
- `close()` — graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional, Type

from openjarvis.voice.barge_in import BargeInCoordinator
from openjarvis.voice.context import ConversationContext
from openjarvis.voice.daemon import AudioDaemonClient
from openjarvis.voice.providers.base import (
    BaseVoiceProvider,
    ProviderEvent,
    ProviderEventType,
)
from openjarvis.voice.providers.deepgram import DeepgramProvider
from openjarvis.voice.providers.gemini import GeminiLiveProvider
from openjarvis.voice.providers.local import LocalProvider

logger = logging.getLogger(__name__)


@dataclass
class SessionEvent:
    """Event emitted by `VoiceSession` for downstream consumers."""

    type: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        return {"type": self.type, "ts": self.ts, **self.data}


# Provider preference order (index 0 = highest priority).
_PROVIDER_CHAIN: List[Type[BaseVoiceProvider]] = [
    GeminiLiveProvider,
    DeepgramProvider,
    LocalProvider,
]

# How long to wait for a provider to deliver a first event before declaring
# it stale and failing over.
_PROVIDER_TIMEOUT = 10.0

# Maximum consecutive errors before failing over to the next provider.
_MAX_ERRORS = 3


class VoiceSession:
    """Real-time voice session with automatic provider failover."""

    def __init__(
        self,
        cfg: dict,
        daemon_url: str = "ws://127.0.0.1:8765",
        connect_daemon: bool = True,
    ) -> None:
        """
        Args:
            cfg: Voice configuration dict. Must contain:
                ``provider`` ("gemini"|"deepgram"|"local"),
                ``gemini_api_key`` / ``deepgram_api_key`` as appropriate.
            daemon_url: URL of the jarvis-audio WebSocket.
            connect_daemon: If False, skip daemon connection (useful for tests).
        """
        self._cfg = cfg
        self._session_id = str(uuid.uuid4())
        self._context = ConversationContext()
        self._context.session_id = self._session_id

        # Event channel from session → WS route handler
        self._event_queue: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=512)
        self._closed = False

        # Current provider index in _PROVIDER_CHAIN.
        self._provider_index = self._initial_provider_index()
        self._provider: Optional[BaseVoiceProvider] = None
        self._error_count = 0

        # Daemon client
        self._daemon = AudioDaemonClient(url=daemon_url, reconnect=True)
        self._connect_daemon = connect_daemon

        # Barge-in coordinator
        self._barge_in = BargeInCoordinator(on_interrupt=self._do_interrupt)
        self._interrupt_requested = False

        # Background tasks
        self._daemon_task: Optional[asyncio.Task] = None
        self._provider_task: Optional[asyncio.Task] = None

    # ---- Public API ---------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def context(self) -> ConversationContext:
        return self._context

    async def start(self) -> None:
        """Connect to the daemon, open the first provider, start pumping."""
        if self._connect_daemon:
            await self._daemon.connect()
        await self._open_provider()
        self._daemon_task = asyncio.create_task(
            self._daemon_pump(), name=f"daemon-pump-{self._session_id[:8]}"
        )
        await self._emit(
            SessionEvent("session_start", {"session_id": self._session_id})
        )
        logger.info(
            "VoiceSession %s started (provider=%s)",
            self._session_id[:8],
            self._provider_name(),
        )

    async def close(self) -> None:
        self._closed = True
        for task in (self._daemon_task, self._provider_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self._provider:
            await self._provider.disconnect()
        if self._connect_daemon:
            await self._daemon.disconnect()
        await self._emit(SessionEvent("session_end", self._context.summary()))
        logger.info("VoiceSession %s closed", self._session_id[:8])

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send PCM16 from an external source to the current provider."""
        if self._provider and self._provider.is_connected:
            await self._provider.send_audio(pcm_chunk)

    async def interrupt(self) -> None:
        self._do_interrupt()

    async def events(self) -> AsyncIterator[dict]:
        while not self._closed or not self._event_queue.empty():
            try:
                evt = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                yield evt.to_dict()
            except asyncio.TimeoutError:
                continue

    # ---- Provider management ------------------------------------------------

    def _initial_provider_index(self) -> int:
        want = self._cfg.get("provider", "gemini")
        names = [cls().__class__.name for cls in _PROVIDER_CHAIN]
        try:
            return names.index(want)
        except ValueError:
            return 0

    def _provider_name(self) -> str:
        if self._provider:
            return self._provider.name
        idx = self._provider_index % len(_PROVIDER_CHAIN)
        return _PROVIDER_CHAIN[idx].name

    async def _open_provider(self) -> None:
        if self._provider:
            await self._provider.disconnect()

        idx = self._provider_index % len(_PROVIDER_CHAIN)
        cls = _PROVIDER_CHAIN[idx]
        self._provider = cls()
        provider_cfg = self._build_provider_cfg(self._provider.name)
        try:
            await self._provider.connect(provider_cfg)
            self._error_count = 0
            self._context.provider = self._provider.name
            logger.info("opened provider: %s", self._provider.name)
            if self._provider_task:
                self._provider_task.cancel()
            self._provider_task = asyncio.create_task(
                self._provider_pump(), name=f"prov-pump-{self._session_id[:8]}"
            )
        except Exception as exc:
            logger.warning("provider %s failed to open: %s", cls.name, exc)
            await self._failover(str(exc))

    async def _failover(self, reason: str) -> None:
        self._provider_index += 1
        if self._provider_index >= len(_PROVIDER_CHAIN):
            logger.error("all providers exhausted — voice session cannot continue")
            await self._emit(
                SessionEvent("error", {"message": "all voice providers failed"})
            )
            return
        new_name = _PROVIDER_CHAIN[self._provider_index % len(_PROVIDER_CHAIN)].name
        logger.info("failing over from provider (reason: %s) → %s", reason, new_name)
        await self._emit(
            SessionEvent(
                "provider_switch",
                {"from": self._provider_name(), "to": new_name, "reason": reason},
            )
        )
        await self._open_provider()

    def _build_provider_cfg(self, provider_name: str) -> dict:
        base = {
            "system_prompt": self._cfg.get("system_prompt", ""),
            "language": self._cfg.get("language", "en-US"),
        }
        if provider_name == "gemini":
            base["api_key"] = self._cfg.get("gemini_api_key", "")
            base["model"] = self._cfg.get(
                "gemini_model", "gemini-live-2.5-flash-preview"
            )
        elif provider_name == "deepgram":
            base["api_key"] = self._cfg.get("deepgram_api_key", "")
            base["tts_voice"] = self._cfg.get("deepgram_tts_voice", "aura-2-luna-en")
        elif provider_name == "local":
            base["whisper_model"] = self._cfg.get("whisper_model", "small.en")
        return base

    # ---- Background pumps ---------------------------------------------------

    async def _daemon_pump(self) -> None:
        """Read daemon events; apply VAD / barge-in; relay audio to provider."""
        try:
            async for evt in self._daemon.events():
                if self._closed:
                    break
                if evt.type == "pcm" and evt.audio:
                    # Raw mic frame → forward to active provider.
                    if self._provider and self._provider.is_connected:
                        await self._provider.send_audio(evt.audio)
                elif evt.type == "vad":
                    state = evt.data.get("state", "")
                    ts_ms = evt.data.get("ts_ms", 0)
                    if state == "speech_start":
                        await self._emit(
                            SessionEvent(
                                "vad", {"state": "speech_start", "ts_ms": ts_ms}
                            )
                        )
                        self._barge_in.on_speech_start()
                    elif state == "speech_end":
                        await self._emit(
                            SessionEvent("vad", {"state": "speech_end", "ts_ms": ts_ms})
                        )
                        # For local provider: flush the utterance buffer.
                        if isinstance(self._provider, LocalProvider):
                            await self._provider.flush_utterance()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("daemon pump error: %s", exc)

    async def _provider_pump(self) -> None:
        """Read events from the active provider and fan them out."""
        if not self._provider:
            return
        try:
            async for evt in self._provider.receive_events():
                if self._closed:
                    break
                await self._handle_provider_event(evt)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error_count += 1
            logger.warning(
                "provider pump error (%d/%d): %s",
                self._error_count,
                _MAX_ERRORS,
                exc,
            )
            if self._error_count >= _MAX_ERRORS and not self._closed:
                await self._failover(str(exc))

    async def _handle_provider_event(self, evt: ProviderEvent) -> None:
        if evt.type == ProviderEventType.TRANSCRIPT_PARTIAL:
            self._context.provider = evt.provider
            await self._emit(
                SessionEvent(
                    "transcript_partial",
                    {"text": evt.text or "", "provider": evt.provider},
                )
            )

        elif evt.type == ProviderEventType.TRANSCRIPT_FINAL:
            text = evt.text or ""
            if text:
                self._context.add_user(text, provider=evt.provider)
            await self._emit(
                SessionEvent(
                    "transcript_final", {"text": text, "provider": evt.provider}
                )
            )

        elif evt.type == ProviderEventType.AUDIO_CHUNK:
            if evt.audio:
                await self._daemon.send_playback(evt.audio)

        elif evt.type == ProviderEventType.TTS_START:
            self._barge_in.tts_started()
            await self._emit(SessionEvent("tts_start", {"provider": evt.provider}))

        elif evt.type == ProviderEventType.TTS_END:
            self._barge_in.tts_ended()
            await self._emit(SessionEvent("tts_end", {"provider": evt.provider}))

        elif evt.type == ProviderEventType.SESSION_END:
            if not self._closed:
                await self._failover("provider session ended unexpectedly")

        elif evt.type == ProviderEventType.ERROR:
            await self._emit(
                SessionEvent(
                    "error",
                    {
                        "message": evt.extra.get("message", "provider error"),
                        "provider": evt.provider,
                    },
                )
            )

    # ---- Barge-in -----------------------------------------------------------

    def _do_interrupt(self) -> None:
        """Synchronous callback from BargeInCoordinator."""
        self._interrupt_requested = True
        # Schedule the async work without blocking the callback.
        asyncio.ensure_future(self._async_interrupt())

    async def _async_interrupt(self) -> None:
        try:
            await self._daemon.stop_playback()
            if self._provider:
                await self._provider.interrupt()
            await self._emit(SessionEvent("user_interrupt", {}))
            logger.info("barge-in interrupt completed")
        except Exception as exc:
            logger.warning("interrupt error: %s", exc)
        finally:
            self._interrupt_requested = False

    # ---- Helpers ------------------------------------------------------------

    async def _emit(self, evt: SessionEvent) -> None:
        try:
            self._event_queue.put_nowait(evt)
        except asyncio.QueueFull:
            logger.debug("session event queue full; dropping %s", evt.type)
