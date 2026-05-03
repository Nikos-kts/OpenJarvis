# Architecture

> Design decisions baked into the codebase. Not a repeat of root CLAUDE.md —
> that covers *how to work*. This covers *why it's shaped this way* and
> *what to preserve when changing it*.

> **History note (2026-05-03):** the upstream openJarvis fork shipped a
> 5-primitive design with an adaptive Learning loop and a separate
> Intelligence module. Phase A.2 of the personalization (see
> [[decisions/0001-strip-vanilla-features]] and
> [[decisions/0002-hardcoded-routing-with-ui-config]]) collapses that into
> 3 primitives plus a `jarvis/` orchestration layer. This file describes
> the post-strip shape.

## Three core primitives

All three communicate via `EventBus` (`src/openjarvis/core/events.py`). The
bus is the seam — don't bypass it with direct cross-primitive imports.

### 1. Engine (`src/openjarvis/engine/`)

Pluggable inference backends implementing `InferenceEngine` ABC (`_base.py`):
`generate()`, `stream()`, `list_models()`, `health()`. Backends include
Ollama, vLLM, SGLang, llama.cpp, MLX, Apple Foundation Models, and cloud
providers (OpenAI, Anthropic, Google, OpenRouter). Auto-discovery probes
all backends and returns healthy ones sorted by preference.

The model catalog (`engine/model_catalog.py`) holds `BUILTIN_MODELS` —
hardcoded metadata (parameters, VRAM, context length, quantisation,
provider, supported engines). `jarvis init` probes hardware and
recommends a model+engine combo from this catalog. Runtime-discovered
models from Ollama/vLLM merge in via `merge_discovered_models`.

### 2. Agents (`src/openjarvis/agents/`)

All agents implement `BaseAgent.run()`. They auto-register via
`@AgentRegistry.register("name")` at import time and are discovered at
runtime. Key agents:

- `OrchestratorAgent` — multi-turn tool-calling
- `NativeReActAgent` — Thought-Action-Observation loop
- `NativeOpenHandsAgent` — CodeAct (generates & executes Python)
- `OperativeAgent` / `MonitorOperativeAgent` — persistent / long-horizon
- `ClaudeCodeAgent` — wraps Claude SDK via Node.js subprocess
- `morning_digest`, `deep_research` — scheduled / research specialists

Per ADR-0002, model selection is hardcoded per agent in user config —
no adaptive routing layer.

### 3. Tools & Memory (`src/openjarvis/tools/`, `tools/storage/`)

20+ tools extending `BaseTool` in `_stubs.py`. Memory backends in
`src/openjarvis/tools/storage/`: SQLite/FTS5 (default), FAISS, ColBERTv2,
BM25, Hybrid RRF (sparse+dense fusion). Don't assume a backend — go
through `BaseTool`.

## Orchestration layer (`src/openjarvis/jarvis/`)

This is *the personalisation*. Not a primitive — a layer over the three
that delivers the user-facing Jarvis persona and the delegate-to-sub-agent
pattern. Modules:

- `agent.py` — `JarvisAgent`, the primary singleton
- `persona.py` — SOUL/MEMORY/USER loader + system-prompt assembly
- `skillset.py` — skill discovery + provisioning for Jarvis
- `toolset.py` — tool provisioning + sensitive-tool filtering
- `delegation.py` — `delegate_to_subagent` tool; routes work to
  user-created sub-agents via `agents/` registry
- `factory.py` — `build_jarvis_agent()` builder
- `state_store.py` — SQLite-backed runtime state (mood, metrics,
  delegation log)
- `routes.py` — FastAPI routes at `/v1/jarvis/*`

Per the project objective (see memory: project_objective): Jarvis
delegates tasks to sub-agents that the user creates with explicit
purpose/tools/skills. Each agent (Jarvis included) has its own model
choice — local or cloud — set per ADR-0002.

## Skills (`src/openjarvis/skills/`)

Skills are loadable units (TOML manifest + tool sequence). The
personalised JarvisAgent picks skills via `jarvis/skillset.py`.

`skills/discovery.py` (~200 LOC, salvaged from the stripped
`learning/agents/`) is a frequency-based pattern miner: given a list of
traces, surface recurring tool sequences as candidate skills. Lightweight,
no ML — directly serves the "Anticipation" persona value (flag patterns
the user hasn't explicitly automated yet).

## Trace recording (`src/openjarvis/traces/`)

Every interaction can be recorded by a `TraceCollector` writing to a
SQLite `TraceStore`. Used for debugging ("what did Jarvis do yesterday")
and as input to `skills/discovery.py`. Not used for adaptive routing —
that's gone.

## Channels & connectors

`src/openjarvis/channels/` holds 18 messaging adapters (post-Phase-C):
Telegram, Slack, Discord, WhatsApp (whatsapp.py + whatsapp_baileys + a
Node bridge), Gmail, Signal, Teams, Matrix, Mattermost, Feishu,
BlueBubbles, Sendblue, Google Chat, IRC, webhook, webchat, email.

`src/openjarvis/connectors/` holds personal data connectors (Gmail,
Calendar, Drive, Apple Notes/Health/Contacts/Music, iMessage, Obsidian,
Notion, Granola, GitHub Notifications, Slack, Strava, Oura, Spotify,
Weather, HackerNews, RSS, etc.) plus the connector framework (oauth,
sync engine, retriever, store).

Full MCP client/server in `src/openjarvis/mcp/` — used both for in-process
tool exposure and for talking to external MCP servers (Gmail/Calendar/
Drive MCPs are wired in already).

## Rust extension (`rust/crates/`)

17 PyO3 crates compiled into `openjarvis_rust` via `_rust_bridge.py`.
Covers security-sensitive and performance-critical paths: ED25519
signing, telemetry, session storage, audio daemon (WebSocket at
`ws://127.0.0.1:8765`), MCP protocol, workflow DAG execution, scheduling.
Don't reimplement in Python — if something belongs in Rust, it likely
already is there.

Must compile before full functionality:

```bash
uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml
```

## Server & frontend

- **FastAPI** (`src/openjarvis/server/`): OpenAI-compatible API at
  `POST /v1/chat/completions`, `GET /v1/models`, `GET /health`,
  WebSocket streaming, channel webhooks. Per-agent config endpoints
  under `/v1/jarvis/*` (per ADR-0002, the UI uses these to set
  per-agent local/cloud model choice).
- **React frontend** (`frontend/src/`): React 19 + TypeScript, Vite
  (port 5173), Zustand, Tailwind CSS v4, shadcn/ui. Pages: Chat,
  Dashboard, Agents, DataSources, Settings, Logs.
- **Desktop**: Tauri 2 wrapper around the same React frontend.

## System composition (`src/openjarvis/system/`)

`SystemBuilder` assembles `JarvisSystem` with pluggable bundles:
`AgentRuntime`, `Scheduling`, `SecurityContext`, `Observability`.
High-level SDK classes: `Jarvis` / `JarvisSystem` in
`src/openjarvis/sdk.py`. The adaptive `LearningOrchestrator` field that
used to live here is gone (Phase A.2.b).

## Key configuration

- `~/.openjarvis/config.toml` — hardware, model/engine prefs per agent,
  API keys, memory backend
- `pyproject.toml` — many optional dep groups; CLI entry:
  `jarvis = openjarvis.cli:main`
- `Makefile` — authoritative reference for all operational commands

## Local-first constraint

Energy, cost, and latency are first-class metrics alongside accuracy.
When evaluating architectural choices, prefer on-device paths. Cloud
fallback is acceptable; cloud-first is not.

---

*Add decisions in `decisions/`. Keep this file lean — one paragraph per
constraint.*
