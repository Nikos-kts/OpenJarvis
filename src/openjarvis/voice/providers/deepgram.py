"""Deepgram assembled voice provider.

STT: Deepgram Nova-3 streaming WS (receive transcripts, send PCM16 audio).
TTS: Deepgram Aura-2 streaming WS or REST (receive PCM16 audio, send text).

This is the cheapest cloud path and the most useful when you need accurate
timestamped transcripts (e.g. UI caption feed). The LLM is handled by the
existing OpenJarvis engine — we receive a final transcript, route it through
the agent, and pipe the text response to Deepgram Aura-2 TTS.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from openjarvis.voice.providers.base import (
    BaseVoiceProvider,
    ProviderEvent,
    ProviderEventType,
)

logger = logging.getLogger(__name__)

_STT_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?encoding=linear16&sample_rate=16000&channels=1"
    "&model=nova-3&smart_format=true&interim_results=true"
    "&utterance_end_ms=1000&vad_events=true"
)
_TTS_URL_TPL = (
    "wss://api.deepgram.com/v1/speak"
    "?model={voice}&encoding=linear16&sample_rate=24000"
)


class DeepgramProvider(BaseVoiceProvider):
    """Assembled STT (Nova-3) + TTS (Aura-2) Deepgram pipeline."""

    name = "deepgram"

    def __init__(self) -> None:
        self._stt_ws = None
        self._tts_ws = None
        self._cfg: dict = {}
        self._connected = False
        self._recv_queue: asyncio.Queue[ProviderEvent] = asyncio.Queue(maxsize=256)
        self._stt_task: Optional[asyncio.Task] = None
        self._tts_task: Optional[asyncio.Task] = None

    # ---- BaseVoiceProvider --------------------------------------------------

    async def connect(self, cfg: dict) -> None:
        self._cfg = cfg
        api_key = cfg.get("api_key", "")
        if not api_key:
            raise ValueError("DeepgramProvider requires 'api_key' in cfg")

        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "The 'websockets' package is required for DeepgramProvider."
            ) from exc

        headers = [("Authorization", f"Token {api_key}")]
        logger.info("connecting to Deepgram STT")
        self._stt_ws = await websockets.connect(_STT_URL, additional_headers=headers)

        voice = cfg.get("tts_voice", "aura-2-luna-en")
        logger.info("connecting to Deepgram TTS (voice=%s)", voice)
        tts_url = _TTS_URL_TPL.format(voice=voice)
        self._tts_ws = await websockets.connect(tts_url, additional_headers=headers)

        self._connected = True
        self._stt_task = asyncio.create_task(self._stt_recv_loop(), name="dg-stt-recv")
        self._tts_task = asyncio.create_task(self._tts_recv_loop(), name="dg-tts-recv")
        logger.info("Deepgram assembled session open")

    async def disconnect(self) -> None:
        self._connected = False
        for task in (self._stt_task, self._tts_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        for ws in (self._stt_ws, self._tts_ws):
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
        self._stt_ws = self._tts_ws = None
        logger.info("Deepgram session closed")

    async def send_audio(self, pcm_chunk: bytes) -> None:
        if not self._connected or not self._stt_ws:
            return
        try:
            await self._stt_ws.send(pcm_chunk)
        except Exception as exc:
            logger.warning("Deepgram send_audio error: %s", exc)
            self._connected = False

    async def receive_events(self) -> AsyncIterator[ProviderEvent]:
        while self._connected or not self._recv_queue.empty():
            try:
                event = await asyncio.wait_for(self._recv_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

    async def interrupt(self) -> None:
        """Cancel TTS by closing and re-opening the TTS socket."""
        if not self._tts_ws:
            return
        try:
            await self._tts_ws.close()
        except Exception:
            pass
        # Drain any buffered TTS audio.
        while not self._recv_queue.empty():
            try:
                item = self._recv_queue.get_nowait()
                if item.type != ProviderEventType.AUDIO_CHUNK:
                    await self._recv_queue.put(item)
            except asyncio.QueueEmpty:
                break

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_text_for_tts(self, text: str) -> None:
        """Push text to the Deepgram TTS socket for speech synthesis."""
        if not self._tts_ws:
            return
        payload = json.dumps({"type": "Speak", "text": text})
        try:
            await self._tts_ws.send(payload)
        except Exception as exc:
            logger.warning("Deepgram TTS send error: %s", exc)

    # ---- Internal receive loops ---------------------------------------------

    async def _stt_recv_loop(self) -> None:
        try:
            async for raw in self._stt_ws:  # type: ignore[union-attr]
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch_stt(msg)
        except Exception as exc:
            logger.warning("Deepgram STT recv loop ended: %s", exc)
        finally:
            self._connected = False
            await self._recv_queue.put(
                ProviderEvent(type=ProviderEventType.SESSION_END, provider=self.name)
            )

    async def _tts_recv_loop(self) -> None:
        try:
            async for raw in self._tts_ws:  # type: ignore[union-attr]
                if isinstance(raw, bytes):
                    if raw:
                        await self._recv_queue.put(
                            ProviderEvent(
                                type=ProviderEventType.AUDIO_CHUNK,
                                audio=raw,
                                provider=self.name,
                            )
                        )
                else:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "Flushed":
                        await self._recv_queue.put(
                            ProviderEvent(
                                type=ProviderEventType.TTS_END,
                                provider=self.name,
                            )
                        )
        except Exception as exc:
            logger.warning("Deepgram TTS recv loop ended: %s", exc)

    async def _dispatch_stt(self, msg: dict) -> None:
        ch = msg.get("channel", {})
        alts = ch.get("alternatives", [{}])
        text = alts[0].get("transcript", "") if alts else ""
        is_final = msg.get("is_final", False)
        if text:
            etype = (
                ProviderEventType.TRANSCRIPT_FINAL
                if is_final
                else ProviderEventType.TRANSCRIPT_PARTIAL
            )
            await self._recv_queue.put(
                ProviderEvent(type=etype, text=text, provider=self.name)
            )
