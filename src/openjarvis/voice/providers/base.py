"""Abstract base for voice providers.

Every provider implements the same async streaming interface so the
`VoiceSession` router can swap between them without the rest of the
pipeline noticing.

Wire-protocol contract (shared with the Rust daemon and the React UI):
- Input:  raw 16 kHz mono PCM16 LE bytes (any chunk size).
- Output: async generator of `ProviderEvent` objects.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional


class ProviderEventType(str, Enum):
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    AUDIO_CHUNK = "audio_chunk"   # raw PCM16 LE bytes destined for playback
    TTS_START = "tts_start"
    TTS_END = "tts_end"
    SESSION_END = "session_end"
    ERROR = "error"


@dataclass
class ProviderEvent:
    type: ProviderEventType
    text: Optional[str] = None
    audio: Optional[bytes] = None
    provider: str = ""
    extra: dict = field(default_factory=dict)


class BaseVoiceProvider(abc.ABC):
    """Abstract base class for voice providers."""

    #: Short identifier shown in logs and emitted as `ProviderEvent.provider`.
    name: str = "base"

    @abc.abstractmethod
    async def connect(self, cfg: dict) -> None:
        """Open the underlying connection (WS, subprocess, …)."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Cleanly close the connection."""

    @abc.abstractmethod
    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send a raw PCM16 chunk to the provider."""

    @abc.abstractmethod
    def receive_events(self) -> AsyncIterator[ProviderEvent]:
        """Async generator yielding `ProviderEvent` objects."""

    @abc.abstractmethod
    async def interrupt(self) -> None:
        """Cancel any pending TTS / generation on the provider side."""

    @property
    def is_connected(self) -> bool:
        return False

    async def __aenter__(self) -> "BaseVoiceProvider":
        await self.connect({})
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()
