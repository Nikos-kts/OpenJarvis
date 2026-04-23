"""Async WebSocket client that talks to the `jarvis-audio` Rust daemon.

Responsibilities:
- Reads the `Ready` handshake on connect.
- Receives binary PCM16 frames → forwards to subscribers.
- Receives JSON VAD / control events → emits them on a queue.
- Writes binary PCM16 frames queued for speaker playback.
- Reconnects automatically with exponential back-off if the daemon
  drops the connection.

Usage::

    client = AudioDaemonClient(url="ws://127.0.0.1:8765")
    await client.connect()

    # Send mic control
    await client.mute(True)

    # Push playback audio
    await client.send_playback(pcm_bytes)

    # Iterate over incoming events
    async for event in client.events():
        if event["type"] == "vad":
            ...

    await client.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

_DEFAULT_URL = "ws://127.0.0.1:8765"
_MAX_BACKOFF = 30.0
_INITIAL_BACKOFF = 0.5


class DaemonEvent:
    """Decoded event from the jarvis-audio daemon."""

    __slots__ = ("type", "data", "audio")

    def __init__(self, type: str, data: dict, audio: Optional[bytes] = None) -> None:
        self.type = type
        self.data = data
        self.audio = audio  # set for PCM16 binary frames, None for JSON events

    def __repr__(self) -> str:
        if self.audio:
            return f"DaemonEvent(type='pcm', bytes={len(self.audio)})"
        return f"DaemonEvent(type={self.type!r}, data={self.data!r})"


class AudioDaemonClient:
    """Persistent async WebSocket client for the jarvis-audio Rust daemon."""

    def __init__(
        self,
        url: str = _DEFAULT_URL,
        reconnect: bool = True,
        max_queue: int = 512,
    ) -> None:
        self._url = url
        self._reconnect = reconnect
        self._ws = None
        self._connected = False
        self._ready: Optional[dict] = None
        self._event_queue: asyncio.Queue[DaemonEvent] = asyncio.Queue(maxsize=max_queue)
        self._recv_task: Optional[asyncio.Task] = None
        self._playback_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
        self._send_task: Optional[asyncio.Task] = None

    # ---- Public API ---------------------------------------------------------

    @property
    def ready_info(self) -> Optional[dict]:
        """The `Ready` message from the daemon, or `None` if not yet connected."""
        return self._ready

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._do_connect()

    async def disconnect(self) -> None:
        self._reconnect = False
        self._connected = False
        for task in (self._recv_task, self._send_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        logger.info("AudioDaemonClient disconnected")

    async def mute(self, value: bool) -> None:
        await self._send_text({"type": "mute_input", "value": value})

    async def stop_playback(self) -> None:
        await self._send_text({"type": "stop_output"})

    async def ping(self) -> None:
        await self._send_text({"type": "ping"})

    async def send_playback(self, pcm: bytes) -> None:
        """Queue PCM16 bytes for speaker playback on the daemon."""
        if not self._connected:
            return
        try:
            self._playback_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            logger.debug("playback queue full; dropping chunk")

    async def events(self) -> AsyncIterator[DaemonEvent]:
        """Async generator of `DaemonEvent` objects from the daemon."""
        while self._connected or not self._event_queue.empty():
            try:
                evt = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                yield evt
            except asyncio.TimeoutError:
                continue

    # ---- Internals ----------------------------------------------------------

    async def _do_connect(self) -> None:
        backoff = _INITIAL_BACKOFF
        while True:
            try:
                import websockets  # type: ignore[import-untyped]

                logger.info("connecting to jarvis-audio at %s", self._url)
                self._ws = await websockets.connect(self._url)
                self._connected = True
                backoff = _INITIAL_BACKOFF

                self._recv_task = asyncio.create_task(
                    self._recv_loop(), name="daemon-recv"
                )
                self._send_task = asyncio.create_task(
                    self._send_loop(), name="daemon-send"
                )
                return  # caller drives the event loop from here

            except Exception as exc:
                self._connected = False
                if not self._reconnect:
                    raise
                logger.warning(
                    "jarvis-audio connection failed (%s); retrying in %.1fs",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _recv_loop(self) -> None:
        try:
            async for msg in self._ws:  # type: ignore[union-attr]
                if isinstance(msg, bytes):
                    await self._event_queue.put(DaemonEvent("pcm", {}, audio=msg))
                else:
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    t = data.get("type", "unknown")
                    if t == "ready":
                        self._ready = data
                        logger.info("jarvis-audio ready: %s", data)
                    await self._event_queue.put(DaemonEvent(t, data))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("daemon recv loop ended: %s", exc)
        finally:
            self._connected = False
            if self._reconnect:
                logger.info("daemon disconnected; scheduling reconnect")
                asyncio.create_task(self._reconnect_loop())

    async def _send_loop(self) -> None:
        try:
            while self._connected:
                try:
                    pcm = await asyncio.wait_for(
                        self._playback_queue.get(), timeout=0.05
                    )
                    if self._ws:
                        await self._ws.send(pcm)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("daemon send loop ended: %s", exc)

    async def _send_text(self, payload: dict) -> None:
        if not self._connected or not self._ws:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("daemon control send error: %s", exc)

    async def _reconnect_loop(self) -> None:
        backoff = _INITIAL_BACKOFF
        while not self._connected and self._reconnect:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)
            try:
                await self._do_connect()
            except Exception:
                pass
