# Architecture

> Design decisions baked into the codebase. Not a repeat of root CLAUDE.md —
> that covers *how to work*. This covers *why it's shaped this way* and *what
> to preserve when changing it*.

## Five core primitives

All five communicate via `EventBus` (`src/openjarvis/core/events.py`). The bus
is the seam between them — don't bypass it with direct cross-primitive imports.

### 1. Intelligence (`src/openjarvis/intelligence/`)
Model catalog (`BUILTIN_MODELS`) with metadata: parameters, VRAM, context length,
quantization. `jarvis init` probes hardware and recommends a model + engine combo.
Runtime-discovered models from Ollama/vLLM merge automatically.

### 2. Engine (`src/openjarvis/engine/`)
Pluggable inference backends implementing `InferenceEngine` ABC (`_base.py`):
`generate()`, `stream()`, `list_models()`, `health()`. Backends: Ollama, vLLM,
SGLang, llama.cpp, MLX, Apple Foundation Models, and cloud providers (OpenAI,
Anthropic, Google, OpenRouter). Auto-discovery probes all backends and returns
healthy ones sorted by preference.

### 3. Agents (`src/openjarvis/agents/`)
All implement `BaseAgent.run()`. Auto-register via `@AgentRegistry.register("name")`
at import time — discovered at runtime. Key agents:
- `OrchestratorAgent` — multi-turn tool-calling
- `NativeReActAgent` — Thought-Action-Observation loop
- `NativeOpenHandsAgent` — CodeAct (generates & executes Python)
- `OperativeAgent` / `MonitorOperativeAgent` — persistent stateful / long-horizon
- `ClaudeCodeAgent` — wraps Claude SDK via Node.js subprocess
- `morning_digest`, `deep_research` — scheduled / research specialists

### 4. Tools & Memory (`src/openjarvis/tools/`, `memory/`)
20+ tools extending `BaseTool` in `_stubs.py`. Memory backends in
`src/openjarvis/tools/storage/`: SQLite/FTS5 (default), FAISS, ColBERTv2, BM25,
Hybrid RRF (sparse+dense fusion). Don't assume a backend — go through BaseTool.

30+ channel adapters (`src/openjarvis/channels/`) and connector adapters
(`src/openjarvis/connectors/`). Full MCP client/server in `src/openjarvis/mcp/`.

### 5. Learning (`src/openjarvis/learning/`, `src/openjarvis/traces/`)
Every interaction produces a `Trace`. `LearningOrchestrator` runs an 8-step
cycle: mine traces → baseline eval → update routing → evolve configs → LoRA/SFT
training → post-learning eval → accept/reject → apply.

Optimization weights: **accuracy 60%, latency 20%, cost 10%, energy 10%.**

Telemetry (`src/openjarvis/telemetry/`) samples energy at 50ms intervals across
NVIDIA (NVML), AMD (amdsmi/RAPL), and Apple Silicon (powermetrics).

## Data flow

```
User (CLI / Browser / Desktop / Channels)
         ↓
   FastAPI Server
         ↓
   Learning Router  (traces → routing recommendations)
         ├→ Agent → Tool calls → Tools (shell, web, code, MCP)
         │       → Inference → Engine (Ollama, vLLM, Cloud, ...)
         │       → Channels (Telegram, Slack, WhatsApp, ...)
         └→ Memory (retrieve context)
         ↓
   Trace recorded → Learning loop → Improves routing & models
         ↓
   Rust Extension (PyO3) — security, telemetry, sessions
```

## Rust extension (`rust/crates/`)
17 PyO3 crates compiled into `openjarvis_rust` via `_rust_bridge.py`. Covers
security-sensitive and performance-critical paths: ED25519 signing, telemetry,
session storage, audio daemon (WebSocket at `ws://127.0.0.1:8765`), MCP
protocol, workflow DAG execution, scheduling. Don't reimplement in Python —
if something belongs in Rust, it likely already is there.

Must compile before full functionality:
```bash
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
```

## Server & frontend
- **FastAPI** (`src/openjarvis/server/`): OpenAI-compatible API at
  `POST /v1/chat/completions`, `GET /v1/models`, `GET /health`, WebSocket
  streaming, channel webhooks.
- **React frontend** (`frontend/src/`): React 19 + TypeScript, Vite (port 5173),
  Zustand, Tailwind CSS v4, shadcn/ui. Pages: Chat, Dashboard, Agents,
  DataSources, Settings, Logs. HTTP + WebSocket.
- **Desktop**: Tauri 2 wrapper around the same React frontend.

## System composition (`src/openjarvis/system/`)
`SystemBuilder` assembles `JarvisSystem` with pluggable bundles: `AgentRuntime`,
`Scheduling`, `SecurityContext`, `Observability`. High-level SDK classes:
`Jarvis` / `JarvisSystem` in `src/openjarvis/sdk.py`.

## Key configuration
- `~/.openjarvis/config.toml` — hardware, model/engine prefs, API keys, memory backend
- `pyproject.toml` — 39 optional dep groups; CLI entry: `jarvis = openjarvis.cli:main`
- `Makefile` — authoritative reference for all operational commands

## Local-first constraint
Energy, cost, and latency are first-class metrics alongside accuracy. When
evaluating architectural choices, prefer on-device paths. Cloud fallback is
acceptable; cloud-first is not.

---

*Add decisions here as they're made. Keep it lean — one paragraph per constraint.*
