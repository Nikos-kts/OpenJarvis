"""Extended API routes for agents, workflows, memory, traces, etc."""

from __future__ import annotations

import concurrent.futures
import inspect
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

# Dedicated single-worker executor for voice LLM inference.
# Using max_workers=1 ensures only one heavy inference job runs at a time,
# preventing multiple concurrent local-model calls from saturating the CPU.
_VOICE_INFERENCE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="voice-infer"
)

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---- Request/Response models ----


class AgentCreateRequest(BaseModel):
    agent_type: str
    tools: Optional[List[str]] = None
    agent_id: Optional[str] = None


class AgentMessageRequest(BaseModel):
    message: str


class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5


class MemoryIndexRequest(BaseModel):
    path: str


class BudgetLimitsRequest(BaseModel):
    max_tokens_per_day: Optional[int] = None
    max_requests_per_hour: Optional[int] = None


class FeedbackScoreRequest(BaseModel):
    trace_id: str
    score: float
    source: str = "api"


class OptimizeRunRequest(BaseModel):
    benchmark: str
    max_trials: int = 20
    optimizer_model: str = "claude-sonnet-4-6"
    max_samples: int = 50


# ---- Agent routes ----

agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])


@agents_router.get("")
async def list_agents(request: Request):
    """List available agent types and running agents."""
    registered = []
    try:
        import openjarvis.agents  # noqa: F401 — side-effect registration
        from openjarvis.core.registry import AgentRegistry

        for key in sorted(AgentRegistry.keys()):
            cls = AgentRegistry.get(key)
            registered.append(
                {
                    "key": key,
                    "class": cls.__name__,
                    "accepts_tools": getattr(cls, "accepts_tools", False),
                }
            )
    except Exception as exc:
        logger.warning("Failed to list registered agents: %s", exc)

    running = []
    try:
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        running = [{"id": k, **v} for k, v in _SPAWNED_AGENTS.items()]
    except ImportError:
        pass

    return {"registered": registered, "running": running}


@agents_router.post("")
async def create_agent(req: AgentCreateRequest, request: Request):
    """Spawn a new agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSpawnTool

        tool = AgentSpawnTool()
        params = {"agent_type": req.agent_type}
        if req.tools:
            params["tools"] = ",".join(req.tools)
        if req.agent_id:
            params["agent_id"] = req.agent_id
        result = tool.execute(**params)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.content)
        return {
            "status": "created",
            "content": result.content,
            "metadata": result.metadata,
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.delete("/{agent_id}")
async def kill_agent(agent_id: str, request: Request):
    """Kill a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentKillTool

        tool = AgentKillTool()
        result = tool.execute(agent_id=agent_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "stopped", "agent_id": agent_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.post("/{agent_id}/message")
async def message_agent(agent_id: str, req: AgentMessageRequest, request: Request):
    """Send a message to a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSendTool

        tool = AgentSendTool()
        result = tool.execute(agent_id=agent_id, message=req.message)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "sent", "content": result.content}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


# ---- Memory routes ----

memory_router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _get_memory_backend(request):
    """Return the app-level memory backend, falling back to a fresh SQLiteMemory."""
    backend = getattr(request.app.state, "memory_backend", None)
    if backend is None:
        try:
            from openjarvis.tools.storage.sqlite import SQLiteMemory

            backend = SQLiteMemory()
        except Exception:
            return None
    return backend


@memory_router.post("/store")
async def memory_store(req: MemoryStoreRequest, request: Request):
    """Store content in memory."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"status": "stored", "note": "no backend available"}
    try:
        backend.store(req.content, metadata=req.metadata or {})
        return {"status": "stored"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/search")
async def memory_search(req: MemorySearchRequest, request: Request):
    """Search memory for relevant content."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"results": []}
    try:
        results = backend.retrieve(req.query, top_k=req.top_k)
        items = [
            {
                "content": r.content,
                "score": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {}),
            }
            for r in results
        ]
        return {"results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/stats")
async def memory_stats(request: Request):
    """Get memory backend statistics."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"entries": 0, "backend": "none", "status": "not_configured"}
    try:
        return {
            "entries": backend.count(),
            "backend": getattr(backend, "backend_id", "unknown"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/config")
async def memory_config(request: Request):
    """Return current memory configuration."""
    try:
        config = getattr(request.app.state, "config", None)
        if config is None:
            from openjarvis.core.config import load_config

            config = load_config()
        backend = getattr(request.app.state, "memory_backend", None)
        return {
            "backend_type": (
                backend.backend_id
                if backend is not None
                else config.memory.default_backend
            ),
            "context_top_k": config.memory.context_top_k,
            "context_min_score": config.memory.context_min_score,
            "context_max_tokens": config.memory.context_max_tokens,
            "context_from_memory": config.agent.context_from_memory,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/index")
async def memory_index(req: MemoryIndexRequest, request: Request):
    """Index files from a path into memory."""
    try:
        from pathlib import Path

        from openjarvis.tools.storage.ingest import ingest_path

        target = Path(req.path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

        backend = _get_memory_backend(request)
        if backend is None:
            raise HTTPException(status_code=503, detail="No memory backend available")

        chunks = ingest_path(target)
        stored = 0
        for chunk in chunks:
            metadata = {"source": getattr(chunk, "source", str(target))}
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)
            backend.store(chunk.content, metadata=metadata)
            stored += 1

        return {"status": "indexed", "chunks_indexed": stored}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Traces routes ----

traces_router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _serialise_trace(trace) -> dict:
    """Convert a Trace dataclass to a frontend-friendly dict."""
    import datetime
    from dataclasses import asdict

    d = asdict(trace)
    d["id"] = d.pop("trace_id", "")
    started = d.pop("started_at", 0.0)
    d["created_at"] = (
        datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).isoformat()
        if started
        else None
    )
    dur = d.pop("total_latency_seconds", 0.0)
    d["duration_ms"] = round(dur * 1000)
    for step in d.get("steps", []):
        st = step.get("step_type")
        if hasattr(st, "value"):
            step["step_type"] = st.value
    return d


@traces_router.get("")
async def list_traces(request: Request, limit: int = 20):
    """List recent traces."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            return {"traces": []}
        traces = store.list_traces(limit=limit)
        items = [_serialise_trace(t) for t in traces]
        return {"traces": items}
    except Exception as exc:
        return {"traces": [], "error": str(exc)}


@traces_router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a specific trace by ID."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace = store.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return _serialise_trace(trace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Telemetry routes ----

telemetry_router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@telemetry_router.get("/stats")
async def telemetry_stats(request: Request):
    """Get aggregated telemetry statistics."""
    try:
        from dataclasses import asdict

        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {"total_requests": 0, "total_tokens": 0}

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            d = asdict(stats)
            d.pop("per_model", None)
            d.pop("per_engine", None)
            d["total_requests"] = d.pop("total_calls", 0)
            return d
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


@telemetry_router.get("/energy")
async def telemetry_energy(request: Request):
    """Get energy monitoring data."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {
                "total_energy_j": 0,
                "energy_per_token_j": 0,
                "avg_power_w": 0,
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            total_energy = stats.total_energy_joules
            total_tokens = stats.total_tokens
            total_latency = stats.total_latency
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


# ---- Skills routes ----

skills_router = APIRouter(prefix="/v1/skills", tags=["skills"])


@skills_router.get("")
async def list_skills(request: Request):
    """List installed skills."""
    try:
        from openjarvis.core.registry import SkillRegistry

        skills = []
        for key in sorted(SkillRegistry.keys()):
            skills.append({"name": key})
        return {"skills": skills}
    except Exception as exc:
        logger.warning("Failed to list skills: %s", exc)
        return {"skills": []}


@skills_router.post("")
async def install_skill(request: Request):
    """Install a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Use TOML files in ~/.openjarvis/skills/",
    }


@skills_router.delete("/{skill_name}")
async def remove_skill(skill_name: str, request: Request):
    """Remove a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Skill removal not yet supported via API",
    }


# ---- Sessions routes ----

sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@sessions_router.get("")
async def list_sessions(request: Request, limit: int = 20):
    """List active sessions."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        sessions = store.recent(limit=limit)
        items = [s.to_dict() if hasattr(s, "to_dict") else str(s) for s in sessions]
        return {"sessions": items}
    except Exception as exc:
        return {"sessions": [], "error": str(exc)}


@sessions_router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a specific session."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict() if hasattr(session, "to_dict") else {"id": session_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Budget routes ----

budget_router = APIRouter(prefix="/v1/budget", tags=["budget"])

_budget_limits: Dict[str, Any] = {
    "max_tokens_per_day": None,
    "max_requests_per_hour": None,
}
_budget_usage: Dict[str, int] = {
    "tokens_today": 0,
    "requests_this_hour": 0,
}


@budget_router.get("")
async def get_budget(request: Request):
    """Get current budget usage and limits."""
    return {"limits": _budget_limits, "usage": _budget_usage}


@budget_router.put("/limits")
async def set_budget_limits(req: BudgetLimitsRequest, request: Request):
    """Update budget limits."""
    if req.max_tokens_per_day is not None:
        _budget_limits["max_tokens_per_day"] = req.max_tokens_per_day
    if req.max_requests_per_hour is not None:
        _budget_limits["max_requests_per_hour"] = req.max_requests_per_hour
    return {"status": "updated", "limits": _budget_limits}


# ---- Prometheus metrics ----

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus-compatible metrics endpoint."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("# no telemetry data\n", media_type="text/plain")

        agg = TelemetryAggregator(db_path)
        stats = agg.summary()

        lines = [
            "# HELP openjarvis_requests_total Total requests processed",
            "# TYPE openjarvis_requests_total counter",
            f"openjarvis_requests_total {stats.get('total_requests', 0)}",
            "# HELP openjarvis_tokens_total Total tokens generated",
            "# TYPE openjarvis_tokens_total counter",
            f"openjarvis_tokens_total {stats.get('total_tokens', 0)}",
            "# HELP openjarvis_latency_avg_ms Average latency in milliseconds",
            "# TYPE openjarvis_latency_avg_ms gauge",
            f"openjarvis_latency_avg_ms {stats.get('avg_latency_ms', 0)}",
        ]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
    except Exception as exc:
        logger.warning("Failed to collect Prometheus metrics: %s", exc)
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("# No metrics available\n", media_type="text/plain")


# ---- WebSocket streaming routes ----

websocket_router = APIRouter(tags=["websocket"])


@websocket_router.websocket("/v1/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """Stream chat responses over a WebSocket connection.

    Accepts JSON messages of the form::

        {"message": "...", "model": "...", "agent": "..."}

    Sends back JSON chunks::

        {"type": "chunk", "content": "..."}   -- per-token streaming
        {"type": "done",  "content": "..."}   -- final assembled response
        {"type": "error", "detail": "..."}    -- on failure
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON"},
                )
                continue

            message = data.get("message")
            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Missing 'message' field"},
                )
                continue

            model = data.get("model") or getattr(
                websocket.app.state,
                "model",
                "default",
            )
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                await websocket.send_json(
                    {"type": "error", "detail": "No engine configured"},
                )
                continue

            messages = [{"role": "user", "content": message}]

            try:
                # Prefer streaming if the engine supports it
                stream_fn = getattr(engine, "stream", None)
                if stream_fn is not None and (
                    inspect.isasyncgenfunction(stream_fn) or callable(stream_fn)
                ):
                    full_content = ""
                    try:
                        gen = stream_fn(messages, model=model)
                        # Handle both async and sync generators
                        if inspect.isasyncgen(gen):
                            async for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                        else:
                            # Sync generator — iterate in a thread to avoid
                            # blocking the event loop
                            for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                    except TypeError:
                        # stream() didn't return an iterable; fall back to
                        # generate()
                        result = engine.generate(messages, model=model)
                        content = (
                            result.get("content", "")
                            if isinstance(
                                result,
                                dict,
                            )
                            else str(result)
                        )
                        full_content = content
                        await websocket.send_json(
                            {"type": "chunk", "content": content},
                        )
                    await websocket.send_json(
                        {"type": "done", "content": full_content},
                    )
                else:
                    # No stream method — single-shot generate
                    result = engine.generate(messages, model=model)
                    content = (
                        result.get("content", "")
                        if isinstance(
                            result,
                            dict,
                        )
                        else str(result)
                    )
                    await websocket.send_json(
                        {"type": "chunk", "content": content},
                    )
                    await websocket.send_json(
                        {"type": "done", "content": content},
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await websocket.send_json(
                    {"type": "error", "detail": str(exc)},
                )
    except WebSocketDisconnect:
        pass  # Client disconnected — nothing to clean up


# ---- Learning routes ----

learning_router = APIRouter(prefix="/v1/learning", tags=["learning"])


@learning_router.get("/stats")
async def learning_stats(request: Request):
    """Return learning system statistics across all sub-policies."""
    result: Dict[str, Any] = {}

    # Skill discovery
    try:
        from openjarvis.learning.agents.skill_discovery import SkillDiscovery

        discovery = SkillDiscovery()
        result["skill_discovery"] = {
            "available": True,
            "discovered_count": len(discovery.discovered_skills),
        }
    except Exception as exc:
        logger.warning("Failed to load skill discovery stats: %s", exc)
        result["skill_discovery"] = {"available": False}

    return result


@learning_router.get("/policy")
async def learning_policy(request: Request):
    """Return current routing policy configuration."""
    result: Dict[str, Any] = {}

    # Load config and extract learning section
    try:
        from openjarvis.core.config import load_config

        config = load_config()
        lc = config.learning
        result["enabled"] = lc.enabled
        result["update_interval"] = lc.update_interval
        result["auto_update"] = lc.auto_update
        result["routing"] = {
            "policy": lc.routing.policy,
            "min_samples": lc.routing.min_samples,
        }
        result["intelligence"] = {
            "policy": lc.intelligence.policy,
        }
        result["agent"] = {
            "policy": lc.agent.policy,
        }
        result["metrics"] = {
            "accuracy_weight": lc.metrics.accuracy_weight,
            "latency_weight": lc.metrics.latency_weight,
            "cost_weight": lc.metrics.cost_weight,
            "efficiency_weight": lc.metrics.efficiency_weight,
        }
    except Exception as exc:
        logger.warning("Failed to load learning config: %s", exc)
        result["enabled"] = False
        result["routing"] = {"policy": "heuristic", "min_samples": 5}
        result["intelligence"] = {"policy": "none"}
        result["agent"] = {"policy": "none"}
        result["metrics"] = {}

    return result


# ---- Speech routes ----

speech_router = APIRouter(prefix="/v1/speech", tags=["speech"])


@speech_router.post("/transcribe")
async def transcribe_speech(request: Request):
    """Transcribe uploaded audio to text."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")

    form = await request.form()
    audio_file = form.get("file")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing 'file' field")

    audio_bytes = await audio_file.read()
    language = form.get("language")

    # Detect format from filename
    filename = getattr(audio_file, "filename", "audio.wav")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "wav"

    import asyncio as _aio
    result = await _aio.to_thread(backend.transcribe, audio_bytes, format=ext, language=language or None)
    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


@speech_router.get("/health")
async def speech_health(request: Request):
    """Check if a speech backend is available."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        return {"available": False, "reason": "No speech backend configured"}
    return {
        "available": backend.health(),
        "backend": backend.backend_id,
    }


@speech_router.get("/wakeword/health")
async def wakeword_health():
    """Check if the openwakeword backend is available."""
    from openjarvis.speech.wakeword import WakeWordDetector

    return {"available": WakeWordDetector.available()}


@speech_router.get("/wake-mode")
async def get_wake_mode(request: Request):
    """Return the current Jarvis wake-up mode and auto-delay."""
    svc = getattr(request.app.state, "clap_boot_service", None)
    if svc is None:
        return {"mode": "off", "auto_delay": 5, "running": False, "jarvis_agent_id": None}
    return svc.get_status()


@speech_router.put("/wake-mode")
async def set_wake_mode(request: Request):
    """Switch the Jarvis wake-up mode at runtime.

    Body JSON: ``{"mode": "clap"|"auto"|"off", "auto_delay": <seconds>}``
    """
    svc = getattr(request.app.state, "clap_boot_service", None)
    if svc is None:
        raise HTTPException(status_code=501, detail="Clap boot service not available")
    body = await request.json()
    mode = body.get("mode")
    auto_delay = body.get("auto_delay")
    tts_model = body.get("tts_model")
    playback_speed = body.get("playback_speed")
    if mode is not None and mode not in ("clap", "auto", "off"):
        raise HTTPException(status_code=422, detail="mode must be 'clap', 'auto', or 'off'")
    if auto_delay is not None:
        try:
            auto_delay = float(auto_delay)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="auto_delay must be a number")
    if tts_model is not None and not isinstance(tts_model, str):
        raise HTTPException(status_code=422, detail="tts_model must be a string")
    if playback_speed is not None:
        try:
            playback_speed = float(playback_speed)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="playback_speed must be a number")
    return svc.set_mode(mode or svc.mode, auto_delay=auto_delay, tts_model=tts_model, playback_speed=playback_speed)


@speech_router.websocket("/wakeword")
async def wakeword_stream(websocket: WebSocket):
    """Stream audio over WebSocket for real-time wake word detection.

    The client should:
      1. Connect to this WebSocket endpoint.
      2. Send raw 16-bit 16 kHz mono PCM audio frames as binary messages.
         Recommended chunk size: 1280 samples = 2560 bytes (80 ms).
      3. Listen for JSON messages:
         - ``{"type": "detected", "score": 0.85}`` — wake word detected
         - ``{"type": "ready"}`` — model loaded, ready for audio
         - ``{"type": "error", "detail": "..."}`` — on failure
      4. After receiving "detected", the client can close or keep streaming.
    """
    import asyncio

    from openjarvis.speech.wakeword import WakeWordDetector

    await websocket.accept()
    _ww_log = logging.getLogger("uvicorn.error")
    _ww_log.info("WakeWord WebSocket accepted")

    if not WakeWordDetector.available():
        _ww_log.warning("WakeWord: openwakeword not available")
        await websocket.send_json(
            {"type": "error", "detail": "openwakeword not installed"}
        )
        await websocket.close()
        return

    try:
        # Initialize detector (will download model on first run)
        _ww_log.info("WakeWord: initializing detector...")
        detector = await asyncio.to_thread(WakeWordDetector, threshold=0.5)
        _ww_log.info("WakeWord: detector ready")
    except Exception as exc:
        _ww_log.error("WakeWord: failed to load model: %s", exc)
        await websocket.send_json(
            {"type": "error", "detail": f"Failed to load model: {exc}"}
        )
        await websocket.close()
        return

    await websocket.send_json({"type": "ready"})

    chunks_received = 0
    _ww_frames_processed = 0
    try:
        while True:
            data = await websocket.receive_bytes()
            chunks_received += 1
            if chunks_received == 1:
                _ww_log.info("WakeWord: first audio chunk received (%d bytes)", len(data))
            elif chunks_received % 500 == 0:
                _ww_log.info("WakeWord: %d chunks received, %d processed", chunks_received, _ww_frames_processed)

            # Process every other chunk (~160 ms resolution) to halve CPU load.
            # openwakeword tolerates dropped frames and will still detect wakewords.
            if chunks_received % 2 == 0:
                continue

            _ww_frames_processed += 1
            scores = await asyncio.to_thread(detector.process_audio, data)

            # Check if any model exceeded threshold
            for model_name, score in scores.items():
                if score >= detector.threshold:
                    _ww_log.info(
                        "WakeWord: DETECTED '%s' score=%.3f (threshold=%.2f) after %d chunks",
                        model_name, score, detector.threshold, chunks_received,
                    )
                    await websocket.send_json(
                        {"type": "detected", "score": round(float(score), 3), "model": model_name}
                    )
                    detector.reset()
                    break
    except WebSocketDisconnect:
        _ww_log.info("WakeWord: client disconnected after %d chunks", chunks_received)
    except Exception as exc:
        _ww_log.error("WakeWord: connection error after %d chunks: %s", chunks_received, exc)
        try:
            await websocket.send_json(
                {"type": "error", "detail": "Connection error"}
            )
        except Exception:
            pass


# ---- Gemini Live voice routes ----

voice_router = APIRouter(prefix="/v1/voice", tags=["voice"])

_voice_log = logging.getLogger("uvicorn.error")

_ALLOWED_LIVE_MODELS = frozenset({
    "gemini-2.5-flash-native-audio-latest",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-3.1-flash-live-preview",
})


@voice_router.get("/live/health")
async def voice_live_health():
    """Check if Gemini Live is available (API key configured)."""
    import os

    has_key = bool(os.environ.get("GEMINI_API_KEY"))
    sdk_ok = False
    try:
        from google import genai  # noqa: F401
        from google.genai import types  # noqa: F401

        sdk_ok = True
    except ImportError:
        pass
    return {"available": has_key and sdk_ok, "has_key": has_key, "sdk": sdk_ok}


@voice_router.websocket("/live")
async def voice_live_stream(websocket: WebSocket):
    """Bidirectional audio streaming via Gemini Live API.

    Protocol (browser ↔ server):
      → Binary messages: raw 16-bit 16 kHz mono PCM audio from mic
      → JSON ``{"type": "config", "voice": "Kore", "system": "..."}``
      ← Binary messages: raw 16-bit 24 kHz mono PCM audio from Gemini
      ← JSON ``{"type": "user_transcript", "text": "..."}``
      ← JSON ``{"type": "assistant_transcript", "text": "..."}``
      ← JSON ``{"type": "turn_complete"}``
      ← JSON ``{"type": "interrupted"}``
      ← JSON ``{"type": "error", "detail": "..."}``
      ← JSON ``{"type": "ready"}``
    """
    import asyncio
    import os

    await websocket.accept()
    _voice_log.info("Voice Live: WebSocket accepted")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        await websocket.send_json(
            {"type": "error", "detail": "GEMINI_API_KEY not configured"}
        )
        await websocket.close()
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        await websocket.send_json(
            {"type": "error", "detail": "google-genai SDK not installed"}
        )
        await websocket.close()
        return

    # Wait for optional config message (voice, system instruction)
    voice_name = "Kore"
    system_text = (
        "You are J.A.R.V.I.S., an advanced AI assistant inspired by the Iron Man films. "
        "Speak in a calm, refined, confident British butler tone. "
        "Be polite, slightly formal, subtly witty, helpful, and composed."
    )
    live_model = "gemini-2.5-flash-native-audio-latest"

    try:
        first_msg = await asyncio.wait_for(websocket.receive(), timeout=2.0)
        if first_msg.get("text"):
            import json as _json

            cfg = _json.loads(first_msg["text"])
            if cfg.get("type") == "config":
                voice_name = cfg.get("voice", voice_name)
                system_text = cfg.get("system", system_text)
                requested_model = cfg.get("model", "")
                if requested_model in _ALLOWED_LIVE_MODELS:
                    live_model = requested_model
    except (asyncio.TimeoutError, Exception):
        # No config message — use defaults
        pass

    # --- Enrich system prompt with memory context ---
    try:
        from datetime import datetime

        memory_backend = _get_memory_backend(websocket)
        memory_snippets: list[str] = []
        if memory_backend is not None:
            try:
                results = memory_backend.retrieve(
                    "user profile preferences context", top_k=5
                )
                for r in results:
                    content = getattr(r, "content", str(r))
                    score = getattr(r, "score", 0.0)
                    if score >= 0.3 and content.strip():
                        memory_snippets.append(content.strip())
            except Exception as exc:
                _voice_log.debug("Voice Live: memory retrieval failed: %s", exc)

        now = datetime.now()
        time_context = (
            f"Current date/time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}. "
        )
        hour = now.hour
        greeting_hint = (
            "It's morning."
            if hour < 12
            else "It's afternoon."
            if hour < 17
            else "It's evening."
        )

        enriched_parts = [system_text.rstrip(".") + "."]
        enriched_parts.append(time_context + greeting_hint)
        if memory_snippets:
            enriched_parts.append(
                "Relevant personal context from memory:\n"
                + "\n".join(f"- {s}" for s in memory_snippets)
            )
        enriched_parts.append(
            "Keep responses conversational and concise — you are speaking aloud, not writing."
        )
        system_text = "\n\n".join(enriched_parts)
    except Exception as exc:
        _voice_log.debug("Voice Live: system prompt enrichment failed: %s", exc)

    _voice_log.info(
        "Voice Live: starting session (voice=%s, model=%s)",
        voice_name,
        live_model,
    )

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name
                )
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text=system_text)]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(),
        ),
    )

    client = genai.Client(api_key=api_key)

    try:
        async with client.aio.live.connect(
            model=live_model, config=config
        ) as session:
            await websocket.send_json({"type": "ready"})
            _voice_log.info("Voice Live: Gemini session ready")

            # --- Forward browser audio → Gemini ---
            async def forward_to_gemini() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("bytes"):
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=msg["bytes"],
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                except WebSocketDisconnect:
                    pass

            # --- Forward Gemini audio/transcripts → browser ---
            async def forward_from_gemini() -> None:
                try:
                    while True:
                        async for response in session.receive():
                            # Handle go_away (server requesting session end)
                            if response.go_away:
                                _voice_log.info("Voice Live: server sent go_away")
                                await websocket.send_json({
                                    "type": "error",
                                    "detail": "Server requested session end."
                                    " Please reconnect.",
                                })
                                return

                            sc = response.server_content
                            if sc is None:
                                continue

                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        await websocket.send_bytes(
                                            part.inline_data.data
                                        )

                            if (
                                hasattr(sc, "input_transcription")
                                and sc.input_transcription
                                and sc.input_transcription.text
                            ):
                                await websocket.send_json(
                                    {
                                        "type": "user_transcript",
                                        "text": sc.input_transcription.text,
                                    }
                                )
                            if (
                                hasattr(sc, "output_transcription")
                                and sc.output_transcription
                                and sc.output_transcription.text
                            ):
                                await websocket.send_json(
                                    {
                                        "type": "assistant_transcript",
                                        "text": sc.output_transcription.text,
                                    }
                                )
                            if sc.interrupted:
                                await websocket.send_json({"type": "interrupted"})
                            if sc.turn_complete:
                                await websocket.send_json({"type": "turn_complete"})
                        _voice_log.debug("Voice Live: receive() iterator ended, re-entering")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _voice_log.error("Voice Live: Gemini receive error: %s", exc)
                    try:
                        await websocket.send_json(
                            {"type": "error", "detail": f"Gemini session error: {exc}"}
                        )
                    except Exception:
                        pass

            fwd_task = asyncio.create_task(forward_to_gemini())
            recv_task = asyncio.create_task(forward_from_gemini())
            try:
                done, pending = await asyncio.wait(
                    [fwd_task, recv_task], return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
            finally:
                fwd_task.cancel()
                recv_task.cancel()

    except WebSocketDisconnect:
        _voice_log.info("Voice Live: client disconnected")
    except Exception as exc:
        _voice_log.error("Voice Live: session error: %s", exc)
        try:
            await websocket.send_json(
                {"type": "error", "detail": str(exc)}
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        _voice_log.info("Voice Live: session ended")


# ---- Voice Engine bridge (Gemini STT → OpenJarvis engine → Gemini TTS) ----


async def _gemini_tts(
    text: str,
    api_key: str,
    voice_name: str = "Kore",
    model: str = "gemini-2.5-flash-preview-tts",
) -> bytes:
    """Synthesize speech via Gemini's generateContent with audio output.

    Returns raw 24 kHz 16-bit mono PCM bytes ready for WebSocket streaming.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )
    # The response contains inline audio data
    audio_bytes = b""
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            audio_bytes += part.inline_data.data
    return audio_bytes


async def _gemini_native_audio_repeat_stream(
    text: str,
    api_key: str,
    voice_name: str = "Kore",
    model: str = "gemini-2.5-flash-native-audio-latest",
) -> AsyncIterator[bytes]:
    """Synthesize speech via a dedicated Gemini Live native-audio session.

    Native-audio models do not support ``generate_content`` for audio output,
    so this helper opens a short-lived Live session and sends a verbatim-read
    prompt as normal client content.
    """
    from google import genai
    from google.genai import types

    prompt = (
        "You are a speech renderer. Read the provided text exactly as written. "
        "Do not add, remove, paraphrase, summarize, or answer anything. "
        "Speak only the exact text between the tags.\n\n"
        "<VERBATIM_TEXT>\n"
        f"{text}\n"
        "</VERBATIM_TEXT>"
    )

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            )
        ),
    )

    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=prompt)],
            ),
            turn_complete=True,
        )

        async for response in session.receive():
            sc = response.server_content
            if sc is None:
                continue

            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        yield part.inline_data.data

            if sc.turn_complete:
                break


def _resolve_voice_managed_jarvis_agent_id(app) -> str | None:
    """Pick the managed Jarvis agent to handle voice requests.

    Priority:
      1) Clap boot service's pinned jarvis_agent_id (if valid)
      2) First non-archived managed agent with agent_type='jarvis'
    """
    manager = getattr(app.state, "agent_manager", None)
    if manager is None:
        return None

    try:
        clap_service = getattr(app.state, "clap_boot_service", None)
        pinned_id = getattr(clap_service, "_jarvis_id", None)
        if pinned_id:
            agent = manager.get_agent(pinned_id)
            if agent and agent.get("status") != "archived":
                return pinned_id
    except Exception:
        pass

    try:
        active = [ag for ag in manager.list_agents() if ag.get("status") != "archived"]

        # Primary: explicit jarvis agent type
        for ag in active:
            if ag.get("agent_type") == "jarvis":
                return ag.get("id")

        # Fallback: user-named Jarvis managed agent (legacy setups)
        for ag in active:
            if str(ag.get("name", "")).strip().lower() == "jarvis":
                return ag.get("id")
    except Exception:
        pass

    return None


@voice_router.websocket("/engine")
async def voice_engine_stream(websocket: WebSocket):
    """Voice-to-engine bridge: Gemini STT → OpenJarvis engine → Gemini TTS.

    Uses Gemini Live only for real-time speech-to-text transcription,
    routes the transcript through the full OpenJarvis engine pipeline
    (memory, complexity analysis, agents, tools), and synthesizes the
    response back to speech via Gemini TTS.

    Protocol (browser ↔ server) — same as /live:
      → Binary messages: raw 16-bit 16 kHz mono PCM audio from mic
      → JSON ``{"type": "config", "voice": "Kore", "engine_model": "llama3.1:8b"}``
      ← Binary messages: raw 16-bit 24 kHz mono PCM audio (TTS output)
      ← JSON ``{"type": "user_transcript", "text": "..."}``
      ← JSON ``{"type": "assistant_transcript", "text": "..."}``
      ← JSON ``{"type": "turn_complete"}``
      ← JSON ``{"type": "interrupted"}``
      ← JSON ``{"type": "error", "detail": "..."}``
      ← JSON ``{"type": "ready"}``
    """
    import asyncio
    import os

    await websocket.accept()
    _voice_log.info("Voice Engine: WebSocket accepted")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        await websocket.send_json(
            {"type": "error", "detail": "GEMINI_API_KEY not configured"}
        )
        await websocket.close()
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        await websocket.send_json(
            {"type": "error", "detail": "google-genai SDK not installed"}
        )
        await websocket.close()
        return

    # --- Parse config ---
    voice_name = "Kore"
    engine_model = ""  # empty = use server default
    tts_mode = "native-audio-repeat"
    tts_model = "gemini-2.5-flash-preview-tts"
    system_text = (
        "You are J.A.R.V.I.S., an advanced AI assistant inspired by the Iron Man films. "
        "Speak in a calm, refined, confident British butler tone. "
        "Be polite, slightly formal, subtly witty, helpful, and composed."
    )
    # Only native-audio models support bidiGenerateContent.
    # They require response_modalities=[AUDIO]; we'll discard Gemini's
    # audio and only use input_audio_transcription for STT.
    live_model = "gemini-2.5-flash-native-audio-latest"

    try:
        first_msg = await asyncio.wait_for(websocket.receive(), timeout=2.0)
        if first_msg.get("text"):
            import json as _json

            cfg = _json.loads(first_msg["text"])
            if cfg.get("type") == "config":
                voice_name = cfg.get("voice", voice_name)
                system_text = cfg.get("system", system_text)
                engine_model = cfg.get("engine_model", "")
                requested_model = cfg.get("stt_model", "") or cfg.get("model", "")
                if requested_model in _ALLOWED_LIVE_MODELS:
                    live_model = requested_model
                requested_tts_mode = cfg.get("tts_mode", "")
                if requested_tts_mode in ("gemini-tts", "native-audio-repeat", "browser-fallback"):
                    tts_mode = requested_tts_mode
                requested_tts_model = cfg.get("tts_model", "")
                if requested_tts_model:
                    tts_model = requested_tts_model
                _voice_log.info(
                    "Voice Engine: config received — voice=%s, engine_model=%s, stt_model=%s, tts_mode=%s, tts_model=%s",
                    voice_name,
                    engine_model or "(default)",
                    live_model,
                    tts_mode,
                    tts_model,
                )
    except (asyncio.TimeoutError, Exception):
        pass

    # --- Get engine, agent, and memory from app state ---
    engine = getattr(websocket.app.state, "engine", None)
    if engine is None:
        await websocket.send_json(
            {"type": "error", "detail": "No engine configured"}
        )
        await websocket.close()
        return
    agent = getattr(websocket.app.state, "agent", None)
    managed_agent_manager = getattr(websocket.app.state, "agent_manager", None)
    managed_agent_executor = getattr(websocket.app.state, "agent_executor", None)
    managed_jarvis_agent_id = _resolve_voice_managed_jarvis_agent_id(websocket.app)

    if not engine_model:
        engine_model = getattr(websocket.app.state, "model", "") or ""

    memory_backend = _get_memory_backend(websocket)
    config_obj = getattr(websocket.app.state, "config", None)

    _voice_log.info(
        "Voice Engine: starting (stt=%s, engine_model=%s, voice=%s)",
        live_model,
        engine_model or "(default)",
        voice_name,
    )

    # --- Configure Gemini Live for STT ---
    # Native-audio models require AUDIO output. We enable
    # input_audio_transcription to get user speech as text,
    # and output_audio_transcription to know when Gemini's turn ends.
    # Gemini's own audio replies are discarded — only the user transcript
    # is routed through the OpenJarvis engine.
    stt_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part(text=(
                "You are a speech transcription assistant. "
                "Acknowledge briefly. The user's speech transcript is what matters."
            ))]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(),
        ),
    )

    client = genai.Client(api_key=api_key)

    # Seed conversation with a system message so the engine knows its role
    from openjarvis.core.types import Message, Role

    conversation_history: list = [
        Message(
            role=Role.SYSTEM,
            content=system_text,
        )
    ]

    try:
        async with client.aio.live.connect(
            model=live_model, config=stt_config
        ) as session:
            await websocket.send_json({"type": "ready"})
            _voice_log.info("Voice Engine: Gemini STT session ready")

            # --- Forward browser audio → Gemini for STT ---
            async def forward_to_gemini() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("bytes"):
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=msg["bytes"],
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                except WebSocketDisconnect:
                    pass

            # --- Listen for transcripts, route through engine, TTS back ---
            async def process_and_respond() -> None:
                current_utterance = ""
                try:
                    while True:
                        async for response in session.receive():
                            if response.go_away:
                                _voice_log.info(
                                    "Voice Engine: Gemini sent go_away"
                                )
                                await websocket.send_json({
                                    "type": "error",
                                    "detail": "STT session ended. Please reconnect.",
                                })
                                return

                            sc = response.server_content
                            if sc is None:
                                continue

                            # Discard Gemini's own audio output — we only
                            # care about the user's input transcription.
                            # (Native-audio models always produce audio
                            #  in response, but we ignore it.)

                            # Collect user speech transcription
                            if (
                                hasattr(sc, "input_transcription")
                                and sc.input_transcription
                                and sc.input_transcription.text
                            ):
                                chunk = sc.input_transcription.text
                                current_utterance += chunk
                                _voice_log.debug(
                                    "Voice Engine: STT chunk: %s",
                                    chunk[:80],
                                )
                                await websocket.send_json({
                                    "type": "user_transcript",
                                    "text": chunk,
                                })

                            if sc.interrupted:
                                _voice_log.info("Voice Engine: interrupted")
                                await websocket.send_json(
                                    {"type": "interrupted"}
                                )
                                current_utterance = ""

                            # turn_complete fires after Gemini finishes
                            # its audio reply. At that point we have the
                            # full user utterance from input_transcription.
                            if sc.turn_complete and current_utterance.strip():
                                utterance = current_utterance.strip()
                                current_utterance = ""
                                _voice_log.info(
                                    "Voice Engine: user said: %s",
                                    utterance[:100],
                                )

                                # === ROUTE THROUGH ENGINE ===
                                try:
                                    conversation_history.append(
                                        Message(
                                            role=Role.USER,
                                            content=utterance,
                                        )
                                    )

                                    # Memory context injection
                                    messages_for_engine = list(
                                        conversation_history
                                    )
                                    if (
                                        config_obj is not None
                                        and memory_backend is not None
                                        and getattr(
                                            config_obj.agent,
                                            "context_from_memory",
                                            False,
                                        )
                                    ):
                                        try:
                                            from openjarvis.tools.storage.context import (
                                                ContextConfig,
                                                inject_context,
                                            )

                                            ctx_cfg = ContextConfig(
                                                top_k=config_obj.memory.context_top_k,
                                                min_score=config_obj.memory.context_min_score,
                                                max_context_tokens=config_obj.memory.context_max_tokens,
                                            )
                                            messages_for_engine = inject_context(
                                                utterance,
                                                messages_for_engine,
                                                memory_backend,
                                                config=ctx_cfg,
                                            )
                                            _voice_log.info(
                                                "Voice Engine: memory injected (%d messages)",
                                                len(messages_for_engine),
                                            )
                                        except Exception as exc:
                                            _voice_log.warning(
                                                "Voice Engine: memory injection failed: %s",
                                                exc,
                                            )
                                    else:
                                        _voice_log.info(
                                            "Voice Engine: no memory injection (config=%s, memory=%s, context_from_memory=%s)",
                                            config_obj is not None,
                                            memory_backend is not None,
                                            getattr(config_obj.agent, "context_from_memory", False)
                                            if config_obj else "N/A",
                                        )

                                    model_to_use = (
                                        engine_model
                                        or getattr(
                                            websocket.app.state,
                                            "model",
                                            "",
                                        )
                                    )

                                    import asyncio as _aio
                                    loop = _aio.get_running_loop()

                                    response_text = ""
                                    if (
                                        managed_agent_manager is not None
                                        and managed_agent_executor is not None
                                        and managed_jarvis_agent_id
                                    ):
                                        _voice_log.info(
                                            "Voice Engine: >>> routing to managed Jarvis agent id=%s",
                                            managed_jarvis_agent_id,
                                        )

                                        def _run_managed_agent_tick() -> str:
                                            # Track last agent->user message before this turn
                                            before = managed_agent_manager.list_messages(
                                                managed_jarvis_agent_id, limit=20,
                                            )
                                            before_latest_ts = max(
                                                (
                                                    m.get("created_at", 0.0)
                                                    for m in before
                                                    if m.get("direction") == "agent_to_user"
                                                ),
                                                default=0.0,
                                            )

                                            # Queue user utterance and run one managed-agent tick
                                            managed_agent_manager.send_message(
                                                managed_jarvis_agent_id,
                                                content=utterance,
                                                mode="immediate",
                                            )
                                            managed_agent_executor.execute_tick(
                                                managed_jarvis_agent_id,
                                            )

                                            # Read newest fresh response from this tick
                                            after = managed_agent_manager.list_messages(
                                                managed_jarvis_agent_id, limit=50,
                                            )
                                            fresh = [
                                                m
                                                for m in after
                                                if m.get("direction") == "agent_to_user"
                                                and m.get("created_at", 0.0) > before_latest_ts
                                            ]
                                            if fresh:
                                                fresh.sort(
                                                    key=lambda m: m.get("created_at", 0.0),
                                                    reverse=True,
                                                )
                                                return str(fresh[0].get("content", "")).strip()

                                            # Fallback to latest response if no timestamp delta found
                                            for m in after:
                                                if m.get("direction") == "agent_to_user":
                                                    return str(m.get("content", "")).strip()
                                            return ""

                                        response_text = await loop.run_in_executor(
                                            _VOICE_INFERENCE_EXECUTOR,
                                            _run_managed_agent_tick,
                                        )

                                        _voice_log.info(
                                            "Voice Engine: <<< managed Jarvis response (%d chars)",
                                            len(response_text),
                                        )

                                    elif agent is not None:
                                        _voice_log.info(
                                            "Voice Engine: >>> calling agent.run() — agent=%s, model=%s, messages=%d",
                                            getattr(agent, "agent_id", type(agent).__name__),
                                            model_to_use,
                                            len(messages_for_engine),
                                        )

                                        from openjarvis.agents._stubs import AgentContext

                                        def _run_agent_with_context() -> str:
                                            ctx = AgentContext()
                                            # Build agent context from prior turns (exclude latest user message)
                                            for prior in messages_for_engine[:-1]:
                                                ctx.conversation.add(prior)

                                            user_input = messages_for_engine[-1].content if messages_for_engine else ""
                                            original_model = getattr(agent, "_model", "")
                                            if model_to_use:
                                                agent._model = model_to_use
                                            try:
                                                result_obj = agent.run(user_input, context=ctx)
                                            finally:
                                                if model_to_use:
                                                    agent._model = original_model

                                            return result_obj.content or ""

                                        # Use the capped single-worker executor so only one
                                        # heavy inference job runs at a time across voice sessions.
                                        response_text = await loop.run_in_executor(
                                            _VOICE_INFERENCE_EXECUTOR,
                                            _run_agent_with_context,
                                        )

                                        _voice_log.info(
                                            "Voice Engine: <<< agent returned response (%d chars)",
                                            len(response_text),
                                        )
                                    else:
                                        _voice_log.info(
                                            "Voice Engine: >>> calling engine.generate() — "
                                            "engine=%s, model=%s, messages=%d",
                                            type(engine).__name__,
                                            model_to_use,
                                            len(messages_for_engine),
                                        )

                                        result = await loop.run_in_executor(
                                            _VOICE_INFERENCE_EXECUTOR,
                                            lambda: engine.generate(
                                                messages_for_engine,
                                                model=model_to_use,
                                                temperature=0.7,
                                                max_tokens=512,
                                            ),
                                        )

                                        _voice_log.info(
                                            "Voice Engine: <<< engine returned: type=%s, keys=%s",
                                            type(result).__name__,
                                            list(result.keys()) if isinstance(result, dict) else "N/A",
                                        )

                                        response_text = (
                                            result.get("content", "")
                                            if isinstance(result, dict)
                                            else str(result)
                                        )

                                    if not response_text:
                                        _voice_log.warning(
                                            "Voice Engine: engine returned empty content, result=%s",
                                            str(result)[:200],
                                        )
                                        response_text = (
                                            "I didn't get a response. "
                                            "Could you try again?"
                                        )

                                    _voice_log.info(
                                        "Voice Engine: response (%d chars): %s",
                                        len(response_text),
                                        response_text[:150],
                                    )

                                    conversation_history.append(
                                        Message(
                                            role=Role.ASSISTANT,
                                            content=response_text,
                                        )
                                    )

                                    # Send text transcript
                                    await websocket.send_json({
                                        "type": "assistant_transcript",
                                        "text": response_text,
                                    })

                                    # TTS: synthesize and send audio
                                    _voice_log.info(
                                        "Voice Engine: >>> calling TTS (voice=%s, mode=%s, text=%d chars)",
                                        voice_name,
                                        tts_mode,
                                        len(response_text),
                                    )
                                    try:
                                        audio_pcm = b""
                                        if tts_mode == "browser-fallback":
                                            _voice_log.info("Voice Engine: browser-fallback mode selected; skipping server audio synthesis")
                                        elif tts_mode == "native-audio-repeat":
                                            # Use Native Audio Dialog as a TTS replacement and
                                            # stream chunks to the browser as soon as they arrive.
                                            n_chunks = 0
                                            async for audio_chunk in _gemini_native_audio_repeat_stream(
                                                response_text,
                                                api_key,
                                                voice_name=voice_name,
                                                model=live_model,
                                            ):
                                                await websocket.send_bytes(audio_chunk)
                                                n_chunks += 1
                                            _voice_log.info(
                                                "Voice Engine: streamed %d native-audio chunks to browser",
                                                n_chunks,
                                            )
                                        else:
                                            audio_pcm = await _gemini_tts(
                                                response_text,
                                                api_key,
                                                voice_name=voice_name,
                                                model=tts_model,
                                            )
                                        _voice_log.info(
                                            "Voice Engine: <<< TTS returned %d bytes of audio",
                                            len(audio_pcm) if audio_pcm else 0,
                                        )
                                        if audio_pcm:
                                            # Send in chunks to allow
                                            # streaming playback
                                            chunk_size = 4800  # 100ms @ 24kHz
                                            n_chunks = 0
                                            for i in range(
                                                0, len(audio_pcm), chunk_size
                                            ):
                                                await websocket.send_bytes(
                                                    audio_pcm[i : i + chunk_size]
                                                )
                                                n_chunks += 1
                                            _voice_log.info(
                                                "Voice Engine: sent %d audio chunks to browser",
                                                n_chunks,
                                            )
                                    except Exception as tts_exc:
                                        _voice_log.warning(
                                            "Voice Engine: TTS failed: %s",
                                            tts_exc,
                                        )
                                        try:
                                            await websocket.send_json({
                                                "type": "assistant_tts_unavailable",
                                                "text": response_text,
                                                "detail": str(tts_exc),
                                            })
                                        except Exception:
                                            pass

                                    await websocket.send_json(
                                        {"type": "turn_complete"}
                                    )

                                except Exception as engine_exc:
                                    _voice_log.error(
                                        "Voice Engine: engine error: %s",
                                        engine_exc,
                                    )
                                    await websocket.send_json({
                                        "type": "assistant_transcript",
                                        "text": f"Engine error: {engine_exc}",
                                    })
                                    await websocket.send_json(
                                        {"type": "turn_complete"}
                                    )

                        _voice_log.debug(
                            "Voice Engine: receive() iterator ended, re-entering"
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _voice_log.error(
                        "Voice Engine: STT receive error: %s", exc
                    )
                    try:
                        await websocket.send_json(
                            {"type": "error", "detail": f"STT error: {exc}"}
                        )
                    except Exception:
                        pass

            fwd_task = asyncio.create_task(forward_to_gemini())
            proc_task = asyncio.create_task(process_and_respond())
            try:
                done, pending = await asyncio.wait(
                    [fwd_task, proc_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
            finally:
                fwd_task.cancel()
                proc_task.cancel()

    except WebSocketDisconnect:
        _voice_log.info("Voice Engine: client disconnected")
    except Exception as exc:
        _voice_log.error("Voice Engine: session error: %s", exc)
        try:
            await websocket.send_json(
                {"type": "error", "detail": str(exc)}
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        _voice_log.info("Voice Engine: session ended")


# ---- Feedback routes ----

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


@feedback_router.post("")
async def submit_feedback(req: FeedbackScoreRequest, request: Request):
    """Submit feedback for a trace."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No trace database")

        store = TraceStore(db_path)
        updated = store.update_feedback(req.trace_id, req.score)
        store.close()

        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Trace '{req.trace_id}' not found"
            )
        return {"status": "recorded", "trace_id": req.trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@feedback_router.get("/stats")
async def feedback_stats(request: Request):
    """Get feedback statistics."""
    return {"total": 0, "mean_score": 0.0}


# ---- Optimize routes ----

optimize_router = APIRouter(prefix="/v1/optimize", tags=["optimize"])


@optimize_router.get("/runs")
async def list_optimize_runs(request: Request):
    """List optimization runs."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"runs": []}

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()
        return {"runs": runs}
    except Exception as exc:
        logger.warning("Failed to list optimization runs: %s", exc)
        return {"runs": []}


@optimize_router.get("/runs/{run_id}")
async def get_optimize_run(run_id: str, request: Request):
    """Get optimization run details."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"run_id": run_id, "status": "not_found"}

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": run.run_id,
            "status": run.status,
            "benchmark": run.benchmark,
            "trials": len(run.trials),
            "best_trial_id": (run.best_trial.trial_id if run.best_trial else None),
        }
    except Exception as exc:
        logger.warning("Failed to get optimization run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "not_found"}


@optimize_router.post("/runs")
async def start_optimize_run(req: OptimizeRunRequest, request: Request):
    """Start a new optimization run."""
    return {"status": "started", "run_id": "placeholder"}


def include_all_routes(app) -> None:
    """Include all extended API routers in a FastAPI app."""
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(traces_router)
    app.include_router(telemetry_router)
    app.include_router(skills_router)
    app.include_router(sessions_router)
    app.include_router(budget_router)
    app.include_router(metrics_router)
    app.include_router(websocket_router)
    app.include_router(learning_router)
    app.include_router(speech_router)
    app.include_router(voice_router)
    app.include_router(feedback_router)
    app.include_router(optimize_router)

    # Agent Manager routes (if available)
    try:
        if hasattr(app.state, "agent_manager") and app.state.agent_manager:
            from openjarvis.server.agent_manager_routes import (  # noqa: PLC0415
                create_agent_manager_router,
            )

            (
                agents_r,
                templates_r,
                global_r,
                tools_r,
                sendblue_r,
            ) = create_agent_manager_router(app.state.agent_manager)
            app.include_router(agents_r)
            app.include_router(templates_r)
            app.include_router(global_r)
            app.include_router(tools_r)
            app.include_router(sendblue_r)

            from openjarvis.server.jarvis_primary_routes import (  # noqa: PLC0415
                create_jarvis_primary_router,
            )

            app.include_router(
                create_jarvis_primary_router(app.state.agent_manager)
            )
    except ImportError:
        pass

    # WebSocket bridge for real-time agent events
    try:
        from openjarvis.core.events import get_event_bus
        from openjarvis.server.ws_bridge import create_ws_router

        ws_router = create_ws_router(get_event_bus())
        app.include_router(ws_router)
    except Exception:
        logger.debug("WebSocket bridge not available", exc_info=True)


__all__ = [
    "include_all_routes",
    "agents_router",
    "memory_router",
    "traces_router",
    "telemetry_router",
    "skills_router",
    "sessions_router",
    "budget_router",
    "metrics_router",
    "websocket_router",
    "learning_router",
    "speech_router",
    "voice_router",
    "feedback_router",
    "optimize_router",
]
