"""Local (privacy mode) voice provider.

STT: faster-whisper (small.en by default) — loaded lazily on first connect.
TTS: Kokoro ONNX — loaded lazily on first connect.

No network egress. Runs entirely in-process (or in a subprocess for CPU
isolation). This is slower than the cloud providers (~400 ms E2E target)
but has zero marginal cost and fully private.

Dependencies (optional, installed separately):
  pip install faster-whisper
  pip install kokoro-onnx
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from openjarvis.voice.providers.base import (
    BaseVoiceProvider,
    ProviderEvent,
    ProviderEventType,
)

logger = logging.getLogger(__name__)


class LocalProvider(BaseVoiceProvider):
    """Privacy-mode provider: faster-whisper STT + Kokoro TTS."""

    name = "local"

    def __init__(self) -> None:
        self._cfg: dict = {}
        self._connected = False
        self._whisper = None
        self._kokoro = None
        self._recv_queue: asyncio.Queue[ProviderEvent] = asyncio.Queue(maxsize=256)
        # PCM buffer: accumulate audio between VAD speech_start/speech_end
        self._audio_buf: bytearray = bytearray()
        self._capturing = False

    # ---- BaseVoiceProvider --------------------------------------------------

    async def connect(self, cfg: dict) -> None:
        self._cfg = cfg
        model_size = cfg.get("whisper_model", "small.en")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_whisper, model_size)
        await loop.run_in_executor(None, self._load_kokoro)
        self._connected = True
        logger.info("LocalProvider ready (whisper=%s)", model_size)

    async def disconnect(self) -> None:
        self._connected = False
        self._whisper = None
        self._kokoro = None
        self._audio_buf.clear()

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Buffer PCM while the VAD is in speech state."""
        if not self._connected:
            return
        # We always buffer and rely on the caller (VoiceSession) to signal
        # utterance boundaries via `flush_utterance`.
        self._audio_buf.extend(pcm_chunk)

    async def receive_events(self) -> AsyncIterator[ProviderEvent]:
        while self._connected or not self._recv_queue.empty():
            try:
                event = await asyncio.wait_for(self._recv_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

    async def interrupt(self) -> None:
        self._audio_buf.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def flush_utterance(self) -> None:
        """Transcribe the buffered PCM and emit events.

        Called by `VoiceSession` when VAD `speech_end` fires, so we only
        run Whisper on complete utterances (not mid-stream).
        """
        if not self._audio_buf or not self._whisper:
            return
        pcm = bytes(self._audio_buf)
        self._audio_buf.clear()

        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, self._transcribe, pcm)
        if text:
            await self._recv_queue.put(
                ProviderEvent(
                    type=ProviderEventType.TRANSCRIPT_FINAL,
                    text=text,
                    provider=self.name,
                )
            )
            # Synthesise response — caller is responsible for calling back
            # with the LLM response text. Here we yield a placeholder so
            # the session knows a transcript is ready.

    async def synthesise(self, text: str) -> None:
        """Run Kokoro TTS and push audio chunks into the queue."""
        if not self._kokoro or not text:
            return
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(None, self._tts, text)
        if audio_bytes:
            await self._recv_queue.put(
                ProviderEvent(type=ProviderEventType.TTS_START, provider=self.name)
            )
            # Emit in 640-byte (20 ms @ 16 kHz) chunks so the playback
            # pipeline can start streaming immediately.
            chunk_size = 640
            for i in range(0, len(audio_bytes), chunk_size):
                await self._recv_queue.put(
                    ProviderEvent(
                        type=ProviderEventType.AUDIO_CHUNK,
                        audio=audio_bytes[i : i + chunk_size],
                        provider=self.name,
                    )
                )
            await self._recv_queue.put(
                ProviderEvent(type=ProviderEventType.TTS_END, provider=self.name)
            )

    # ---- Sync helpers (run in executor) -------------------------------------

    def _load_whisper(self, model_size: str) -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            self._whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info("faster-whisper model loaded: %s", model_size)
        except ImportError:
            logger.warning(
                "faster-whisper not installed; LocalProvider STT unavailable. "
                "Install with: pip install faster-whisper"
            )

    def _load_kokoro(self) -> None:
        try:
            import kokoro_onnx  # type: ignore[import-untyped]

            self._kokoro = kokoro_onnx.Kokoro()
            logger.info("Kokoro ONNX TTS loaded")
        except ImportError:
            logger.warning(
                "kokoro-onnx not installed; LocalProvider TTS unavailable. "
                "Install with: pip install kokoro-onnx"
            )

    def _transcribe(self, pcm_bytes: bytes) -> str:
        if not self._whisper:
            return ""
        # faster-whisper expects a numpy float32 array or a file-like WAV.
        try:
            import numpy as np  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("numpy not available; cannot transcribe")
            return ""

        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self._whisper.transcribe(samples, language="en", vad_filter=False)
        return " ".join(s.text.strip() for s in segs)

    def _tts(self, text: str) -> Optional[bytes]:
        if not self._kokoro:
            return None
        try:
            samples, sample_rate = self._kokoro.create(
                text, voice="af_bella", speed=1.0
            )
            # Resample to 16 kHz if needed, then convert to PCM16 LE.
            import numpy as np  # type: ignore[import-untyped]

            if sample_rate != 16_000:
                import scipy.signal as signal  # type: ignore[import-untyped]

                target = int(len(samples) * 16_000 / sample_rate)
                samples = signal.resample(samples, target)
            pcm16 = (samples * 32767).astype(np.int16)
            return pcm16.tobytes()
        except Exception as exc:
            logger.warning("Kokoro TTS error: %s", exc)
            return None
