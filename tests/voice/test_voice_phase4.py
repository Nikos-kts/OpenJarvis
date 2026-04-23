"""Unit tests for the Phase 4 voice pipeline.

These tests exercise pure-Python modules only — no audio hardware, no
network calls, no Rust daemon required. Providers that need external WS
connections are bypassed with stubs.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from openjarvis.voice.barge_in import BargeInCoordinator
from openjarvis.voice.context import ConversationContext
from openjarvis.voice.providers.base import (
    BaseVoiceProvider,
    ProviderEvent,
)
from openjarvis.voice.providers.local import LocalProvider
from openjarvis.voice.session import VoiceSession

# ─── ConversationContext ─────────────────────────────────────────────────────


class TestConversationContext:
    def test_add_turns_and_retrieve(self):
        ctx = ConversationContext()
        ctx.add_user("hello", provider="gemini")
        ctx.add_assistant("hi there", provider="gemini")
        assert len(ctx.turns) == 2
        assert ctx.turns[0].role == "user"
        assert ctx.turns[1].role == "assistant"

    def test_last_user_text(self):
        ctx = ConversationContext()
        ctx.add_user("first")
        ctx.add_assistant("reply")
        ctx.add_user("second")
        assert ctx.last_user_text() == "second"

    def test_last_assistant_text(self):
        ctx = ConversationContext()
        ctx.add_user("u")
        ctx.add_assistant("a1")
        ctx.add_assistant("a2")
        assert ctx.last_assistant_text() == "a2"

    def test_max_turns_eviction(self):
        ctx = ConversationContext(max_turns=4)
        for i in range(10):
            ctx.add_user(f"u{i}")
        assert len(ctx.turns) == 4
        assert ctx.turns[0].text == "u6"
        assert ctx.turns[-1].text == "u9"

    def test_to_messages_format(self):
        ctx = ConversationContext()
        ctx.add_user("hello")
        ctx.add_assistant("world")
        msgs = ctx.to_messages()
        assert msgs == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]

    def test_clear(self):
        ctx = ConversationContext()
        ctx.add_user("x")
        ctx.clear()
        assert ctx.turns == []
        assert ctx.last_user_text() is None

    def test_last_n(self):
        ctx = ConversationContext()
        for i in range(5):
            ctx.add_user(f"u{i}")
        last = ctx.last_n(3)
        assert len(last) == 3
        assert last[-1].text == "u4"

    def test_summary_keys(self):
        ctx = ConversationContext()
        ctx.session_id = "test-session"
        ctx.add_user("hi")
        s = ctx.summary()
        assert s["session_id"] == "test-session"
        assert s["turns"] == 1
        assert "duration_s" in s


# ─── BargeInCoordinator ───────────────────────────────────────────────────────


class TestBargeInCoordinator:
    def _make(self, grace: float = 0.0):
        triggered = []
        coord = BargeInCoordinator(
            on_interrupt=lambda: triggered.append(True),
            anti_feedback_grace=grace,
        )
        return coord, triggered

    def test_no_interrupt_when_not_playing(self):
        coord, triggered = self._make()
        fired = coord.on_speech_start()
        assert not fired
        assert triggered == []

    def test_interrupt_fires_when_playing(self):
        coord, triggered = self._make(grace=0.0)
        coord.tts_started()
        fired = coord.on_speech_start()
        assert fired
        assert triggered == [True]

    def test_no_double_interrupt(self):
        coord, triggered = self._make(grace=0.0)
        coord.tts_started()
        coord.on_speech_start()
        fired_again = coord.on_speech_start()
        assert not fired_again
        assert len(triggered) == 1

    def test_grace_period_suppresses(self):
        coord, triggered = self._make(grace=10.0)
        coord.tts_started()
        # Speech immediately after TTS start — within grace period.
        fired = coord.on_speech_start()
        assert not fired
        assert triggered == []

    def test_tts_ended_clears_state(self):
        coord, triggered = self._make(grace=0.0)
        coord.tts_started()
        coord.tts_ended()
        fired = coord.on_speech_start()
        assert not fired

    def test_reset(self):
        coord, triggered = self._make(grace=0.0)
        coord.tts_started()
        coord.reset()
        assert not coord._playing


# ─── ProviderBase stubs ───────────────────────────────────────────────────────


class _StubProvider(BaseVoiceProvider):
    name = "stub"

    def __init__(self):
        self._connected = False
        self.sent_audio: list[bytes] = []
        self.interrupted = False
        self._events: list[ProviderEvent] = []

    async def connect(self, cfg):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def send_audio(self, pcm):
        self.sent_audio.append(pcm)

    async def receive_events(self) -> AsyncIterator[ProviderEvent]:
        for evt in self._events:
            yield evt

    async def interrupt(self):
        self.interrupted = True

    @property
    def is_connected(self):
        return self._connected


class TestBaseProvider:
    def test_stub_connect_disconnect(self):
        async def run():
            p = _StubProvider()
            await p.connect({})
            assert p.is_connected
            await p.disconnect()
            assert not p.is_connected

        asyncio.get_event_loop().run_until_complete(run())

    def test_stub_send_audio(self):
        async def run():
            p = _StubProvider()
            await p.connect({})
            await p.send_audio(b"\x00\x01")
            assert p.sent_audio == [b"\x00\x01"]

        asyncio.get_event_loop().run_until_complete(run())

    def test_stub_interrupt(self):
        async def run():
            p = _StubProvider()
            await p.connect({})
            await p.interrupt()
            assert p.interrupted

        asyncio.get_event_loop().run_until_complete(run())


# ─── PCM framing helpers (ws.py equivalents) ─────────────────────────────────


def _pcm_to_bytes(samples):
    import struct
    return b"".join(struct.pack("<h", s) for s in samples)


def _bytes_to_pcm(data):
    import struct
    count = len(data) // 2
    return list(struct.unpack_from(f"<{count}h", data))


class TestPcmFraming:
    def test_round_trip(self):
        samples = [0, 1, -1, 32767, -32768, 100, -100]
        assert _bytes_to_pcm(_pcm_to_bytes(samples)) == samples

    def test_empty(self):
        assert _pcm_to_bytes([]) == b""
        assert _bytes_to_pcm(b"") == []

    def test_odd_trailing_byte_ignored(self):
        data = _pcm_to_bytes([1, 2, 3]) + b"\xff"
        samples = _bytes_to_pcm(data)
        assert len(samples) == 3


# ─── VoiceSession (mock daemon + provider) ───────────────────────────────────


class _StubDaemon:
    """Minimal stand-in for AudioDaemonClient."""

    def __init__(self):
        self.playback: list[bytes] = []
        self.stopped = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_playback(self, pcm):
        self.playback.append(pcm)

    async def stop_playback(self):
        self.stopped = True

    async def mute(self, value):
        pass

    async def events(self):
        while True:
            try:
                evt = self._queue.get_nowait()
                yield evt
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)

    def push(self, evt):
        self._queue.put_nowait(evt)


class TestVoiceSessionFailover:
    """Verify provider failover when the first provider fails to open."""

    def test_failover_on_connect_error(self):
        """If provider[0] raises on connect, provider[1] should be used."""
        from openjarvis.voice import session as sess_mod

        class FailProvider(BaseVoiceProvider):
            name = "gemini"

            async def connect(self, cfg):
                raise RuntimeError("no key")

            async def disconnect(self):
                pass

            async def send_audio(self, pcm):
                pass

            async def receive_events(self):
                return
                yield  # make it a generator

            async def interrupt(self):
                pass

        class OkProvider(_StubProvider):
            name = "deepgram"

        # Monkey-patch the chain for this test.
        original = sess_mod._PROVIDER_CHAIN[:]
        sess_mod._PROVIDER_CHAIN[:] = [FailProvider, OkProvider, LocalProvider]

        try:
            async def run():
                stub_daemon = _StubDaemon()
                session = VoiceSession(
                    cfg={"provider": "gemini"},
                    daemon_url="ws://127.0.0.1:9999",
                    connect_daemon=False,
                )
                session._daemon = stub_daemon
                await session.start()
                # After start, provider should have fallen over to deepgram.
                assert session.context.provider == "deepgram"
                await session.close()

            asyncio.get_event_loop().run_until_complete(run())
        finally:
            sess_mod._PROVIDER_CHAIN[:] = original

    def test_session_id_is_uuid(self):
        import uuid

        session = VoiceSession(cfg={}, connect_daemon=False)
        uuid.UUID(session.session_id)  # raises if not valid UUID

    def test_context_is_fresh(self):
        session = VoiceSession(cfg={}, connect_daemon=False)
        assert len(session.context.turns) == 0
