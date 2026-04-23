"""FastAPI voice routes — Phase 4.

Endpoints:
  POST /v1/voice/start       — start a new voice session.
  POST /v1/voice/stop        — stop the active session.
  POST /v1/voice/interrupt   — trigger a programmatic barge-in.
  GET  /v1/voice/status      — current session state.
  WS   /v1/voice/ws          — bidirectional PCM16 relay (browser → daemon).
  WS   /v1/voice/events      — server-sent session events (transcripts, VAD, …).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---- Request / response models ----------------------------------------------


class VoiceStartRequest(BaseModel):
    daemon_url: str = "ws://127.0.0.1:8765"


class VoiceStartResponse(BaseModel):
    session_id: str
    provider: str


class VoiceStatusResponse(BaseModel):
    active: bool
    session_id: Optional[str] = None
    provider: Optional[str] = None
    turns: int = 0


# ---- Session registry (one active session per server process) ---------------


class _SessionRegistry:
    def __init__(self) -> None:
        self._session = None
        self._lock = asyncio.Lock()

    async def start(self, cfg: dict, daemon_url: str):
        from openjarvis.voice.session import VoiceSession

        async with self._lock:
            if self._session is not None:
                await self._session.close()
            session = VoiceSession(cfg=cfg, daemon_url=daemon_url, connect_daemon=True)
            await session.start()
            self._session = session
            return session

    async def stop(self) -> None:
        async with self._lock:
            if self._session:
                await self._session.close()
                self._session = None

    def get(self):
        return self._session


_registry = _SessionRegistry()


# ---- Router factory ---------------------------------------------------------


def create_voice_router() -> APIRouter:
    router = APIRouter(prefix="/v1/voice", tags=["voice"])

    @router.post("/start", response_model=VoiceStartResponse)
    async def start_voice(body: VoiceStartRequest, request: Request):
        cfg = _build_cfg(request)
        try:
            session = await _registry.start(cfg, body.daemon_url)
        except Exception as exc:
            logger.warning("failed to start voice session: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return VoiceStartResponse(
            session_id=session.session_id, provider=session.context.provider
        )

    @router.post("/stop")
    async def stop_voice():
        await _registry.stop()
        return {"ok": True}

    @router.post("/interrupt")
    async def interrupt_voice():
        session = _registry.get()
        if not session:
            raise HTTPException(status_code=404, detail="no active voice session")
        await session.interrupt()
        return {"ok": True}

    @router.get("/status", response_model=VoiceStatusResponse)
    async def voice_status():
        session = _registry.get()
        if not session:
            return VoiceStatusResponse(active=False)
        ctx = session.context
        return VoiceStatusResponse(
            active=True,
            session_id=session.session_id,
            provider=ctx.provider,
            turns=len(ctx.turns),
        )

    @router.websocket("/ws")
    async def voice_ws(websocket: WebSocket):
        """Bidirectional PCM16 relay between a browser/app and the voice session.

        Binary frames → forwarded to the active provider as mic audio.
        Text frames   → JSON control (same protocol as jarvis-audio WS).
        """
        await websocket.accept()
        session = _registry.get()
        if not session:
            err_msg = json.dumps({"type": "error", "message": "no active session"})
            await websocket.send_text(err_msg)
            await websocket.close()
            return

        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg and msg["bytes"]:
                    await session.send_audio(msg["bytes"])
                elif "text" in msg and msg["text"]:
                    try:
                        data = json.loads(msg["text"])
                        if data.get("type") == "interrupt":
                            await session.interrupt()
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("voice_ws error: %s", exc)

    @router.websocket("/events")
    async def voice_events(websocket: WebSocket):
        """Server-sent stream of session events (transcripts, VAD, TTS state)."""
        await websocket.accept()
        session = _registry.get()
        if not session:
            err_msg = json.dumps({"type": "error", "message": "no active session"})
            await websocket.send_text(err_msg)
            await websocket.close()
            return

        try:
            async for evt in session.events():
                try:
                    await websocket.send_text(json.dumps(evt))
                except Exception:
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("voice_events error: %s", exc)

    return router


# ---- Helpers ----------------------------------------------------------------


def _build_cfg(request: Request) -> Dict[str, Any]:
    """Pull speech config from app.state → pass to VoiceSession."""
    try:
        cfg_svc = getattr(request.app.state, "config_service", None)
        if cfg_svc is not None:
            jarvis_cfg = cfg_svc.config
            speech = getattr(jarvis_cfg, "speech", None)
            if speech:
                return {
                    "provider": getattr(speech, "provider", "gemini"),
                    "gemini_api_key": getattr(speech, "gemini_api_key", ""),
                    "gemini_model": getattr(
                        speech, "gemini_model", "gemini-live-2.5-flash-preview"
                    ),
                    "language": getattr(speech, "language", "en-US"),
                    "vad_threshold": getattr(speech, "vad_threshold", 0.5),
                    "sample_rate": getattr(speech, "sample_rate", 16_000),
                }
    except Exception as exc:
        logger.debug("could not read speech config from app state: %s", exc)
    return {"provider": "gemini"}
