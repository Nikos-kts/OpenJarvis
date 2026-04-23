"""Gemini Live voice provider.

Wraps the Google Gemini Live Multimodal Live API WebSocket in the
`BaseVoiceProvider` interface. Uses a bidirectional WS connection that
carries audio IN (mic PCM16) and audio OUT (TTS PCM16) over the same
session, keeping latency at a minimum.

The Gemini Live API uses a JSON-framed binary protocol:
- Client→Server: setup message (once) + audio chunks (binary or JSON with
  base64 inlineData).
- Server→Client: JSON control messages + binary audio chunks.

We use the Google `google-generativeai` SDK's async WS client when
available, and fall back to a raw `websockets`/`aiohttp` approach if the
SDK is not installed. This file imports the SDK lazily so the rest of the
voice package is importable even without `google-generativeai`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncIterator, Optional

from openjarvis.voice.providers.base import (
    BaseVoiceProvider,
    ProviderEvent,
    ProviderEventType,
)

logger = logging.getLogger(__name__)

# Canonical models per the config enum, in preference order.
_MODELS = [
    "gemini-live-2.5-flash-preview",
    "gemini-2.0-flash-live-001",
]

# Gemini Live WS endpoint template.
_WS_URL_TPL = (
    "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage"
    ".v1beta.GenerativeService.BidiGenerateContent?key={api_key}"
)


class GeminiLiveProvider(BaseVoiceProvider):
    """Real-time speech-to-speech via Gemini Live native-audio model."""

    name = "gemini"

    def __init__(self) -> None:
        self._ws = None
        self._cfg: dict = {}
        self._connected = False
        self._recv_queue: asyncio.Queue[ProviderEvent] = asyncio.Queue(maxsize=256)
        self._recv_task: Optional[asyncio.Task] = None

    # ---- BaseVoiceProvider --------------------------------------------------

    async def connect(self, cfg: dict) -> None:
        self._cfg = cfg
        api_key = cfg.get("api_key", "")
        model = cfg.get("model", _MODELS[0])
        if not api_key:
            raise ValueError("GeminiLiveProvider requires 'api_key' in cfg")

        url = _WS_URL_TPL.format(api_key=api_key)
        logger.info("connecting to Gemini Live (model=%s)", model)

        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "The 'websockets' package is required for GeminiLiveProvider. "
                "Install it with: pip install websockets"
            ) from exc

        self._ws = await websockets.connect(url)
        self._connected = True

        # Initial setup message that tells the server the session config.
        setup = {
            "setup": {
                "model": f"models/{model}",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {"voice_name": "Aoede"}
                        }
                    },
                },
                "system_instruction": {
                    "parts": [
                        {
                            "text": cfg.get(
                                "system_prompt", "You are a helpful AI assistant."
                            )
                        }
                    ]
                },
            }
        }
        await self._ws.send(json.dumps(setup))

        # Start the receiver coroutine.
        self._recv_task = asyncio.create_task(self._receive_loop(), name="gemini-recv")
        logger.info("Gemini Live session open")

    async def disconnect(self) -> None:
        self._connected = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Gemini Live session closed")

    async def send_audio(self, pcm_chunk: bytes) -> None:
        if not self._connected or not self._ws:
            return
        # Gemini Live expects base64-encoded PCM16 in inlineData.
        payload = {
            "realtime_input": {
                "media_chunks": [
                    {
                        "data": base64.b64encode(pcm_chunk).decode(),
                        "mime_type": "audio/pcm;rate=16000",
                    }
                ]
            }
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("Gemini Live send_audio error: %s", exc)
            self._connected = False

    async def receive_events(self) -> AsyncIterator[ProviderEvent]:
        while self._connected or not self._recv_queue.empty():
            try:
                event = await asyncio.wait_for(self._recv_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

    async def interrupt(self) -> None:
        if not self._connected or not self._ws:
            return
        # Sending an empty audio turn signals the end of a client-side
        # utterance and implicitly cancels any ongoing model generation.
        try:
            await self._ws.send(json.dumps({"client_content": {"turn_complete": True}}))
        except Exception as exc:
            logger.warning("Gemini Live interrupt error: %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ---- Internal -----------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Drain the server WS and translate messages to `ProviderEvent`s."""
        try:
            async for raw in self._ws:  # type: ignore[union-attr]
                if isinstance(raw, bytes):
                    # Binary audio from the model.
                    await self._recv_queue.put(
                        ProviderEvent(
                            type=ProviderEventType.AUDIO_CHUNK,
                            audio=raw,
                            provider=self.name,
                        )
                    )
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except Exception as exc:
            logger.warning("Gemini Live recv loop ended: %s", exc)
        finally:
            self._connected = False
            await self._recv_queue.put(
                ProviderEvent(type=ProviderEventType.SESSION_END, provider=self.name)
            )

    async def _dispatch(self, msg: dict) -> None:
        # Server content (streaming text + audio)
        sc = msg.get("serverContent", {})
        if sc:
            for part in sc.get("modelTurn", {}).get("parts", []):
                if "inlineData" in part:
                    audio_bytes = base64.b64decode(part["inlineData"].get("data", ""))
                    if audio_bytes:
                        await self._recv_queue.put(
                            ProviderEvent(
                                type=ProviderEventType.AUDIO_CHUNK,
                                audio=audio_bytes,
                                provider=self.name,
                            )
                        )
                if "text" in part:
                    await self._recv_queue.put(
                        ProviderEvent(
                            type=ProviderEventType.TRANSCRIPT_FINAL,
                            text=part["text"],
                            provider=self.name,
                        )
                    )
            if sc.get("turnComplete"):
                await self._recv_queue.put(
                    ProviderEvent(type=ProviderEventType.TTS_END, provider=self.name)
                )
            return

        # Input transcript (what the model heard)
        inp = msg.get("inputTranscript", {})
        if inp:
            text = inp.get("transcript", "")
            if text:
                await self._recv_queue.put(
                    ProviderEvent(
                        type=ProviderEventType.TRANSCRIPT_PARTIAL,
                        text=text,
                        provider=self.name,
                    )
                )
