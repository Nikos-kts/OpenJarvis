# OpenJarvis — Project Overview

## What is OpenJarvis?

A Stanford research project (Hazy Research / Scaling Intelligence Lab) for **local-first personal AI**. The core idea: run AI agents entirely on your device — calling the cloud only when necessary — while tracking energy, cost, and latency as first-class metrics alongside accuracy.

- **GitHub**: https://github.com/open-jarvis/OpenJarvis
- **Docs**: https://open-jarvis.github.io/OpenJarvis/
- **Project site**: https://scalingintelligence.stanford.edu/blogs/openjarvis/
- **License**: Apache 2.0
- **Languages**: Python 80.7%, Rust 9.9%, TypeScript 8.0%

---

## Frontend

There are two frontend surfaces:

### 1. Browser Dashboard (`frontend/`)

- **Stack**: React 19 + TypeScript + Vite, Zustand for state, Tailwind CSS v4, shadcn/ui components
- **Pages**:
  - `ChatPage` — main chat interface with streaming responses, tool call cards, and message bubbles
  - `DashboardPage` — real-time GPU/CPU/memory pulse, cost savings and efficiency metrics
  - `AgentsPage` — configure and manage which agent handles queries
  - `DataSourcesPage` — manage knowledge base / connector sources
  - `SettingsPage` — configure API URL, temperature, max tokens
  - `LogsPage` — view traces and telemetry history
  - `GetStartedPage` — onboarding wizard
- **Communication**: Calls the backend via HTTP to `POST /v1/chat/completions` (OpenAI-compatible) and uses a **WebSocket bridge** for token-by-token streaming. The API base URL is configurable via `VITE_API_URL`.
- **Persistence**: Conversations and settings stored in `localStorage`; analytics go to Supabase.

### 2. Desktop App (`desktop/`)

- **Stack**: Tauri 2 (Rust) wrapping the same React frontend via IPC
- Cross-platform: macOS, Linux, Windows
- The Tauri backend detects the local server port and passes it to the React app

---

## Backend

The backend is Python (~81%), with a Rust extension for performance-critical paths (~10%), organized around **five primitives**:

### Core Infrastructure (`core/`)

- `EventBus` — thread-safe pub/sub that connects all primitives. Events include `INFERENCE_START/END`, `TOOL_CALL_START/END`, `MEMORY_STORE/RETRIEVE`, `TRACE_STEP`, `SECURITY_SCAN`, etc.
- `Registry pattern` — all extensible components (engines, agents, tools, channels) register with a typed decorator (`@AgentRegistry.register("name")`), making them auto-discoverable at runtime without factory changes.
- `JarvisConfig` — loaded from `~/.openjarvis/config.toml`, includes hardware detection.

---

### Primitive 1 — Intelligence (`intelligence/`)

A **model catalog** (`BUILTIN_MODELS`) with metadata: parameter count, VRAM, context length, quantization. `jarvis init` probes the hardware and recommends the best model + engine combination. Runtime-discovered models (from running Ollama/vLLM) are merged into the `ModelRegistry` automatically.

---

### Primitive 2 — Engine (`engine/`)

The **inference runtime layer**. All backends implement the same `InferenceEngine` ABC (`generate()`, `stream()`, `list_models()`, `health()`):

| Backend | Details |
|---|---|
| Ollama | Native HTTP API |
| vLLM / SGLang / llama.cpp / MLX / LM Studio | OpenAI-compatible |
| Apple Foundation Models | CoreML via shim |
| Cloud (OpenAI, Anthropic, Google, etc.) | API keys required |

Engine discovery probes all backends and returns healthy ones sorted by user preference, with automatic fallback.

---

### Primitive 3 — Agents (`agents/`)

Pluggable reasoning patterns, all implementing `BaseAgent.run()`:

| Agent | Type | What it does |
|---|---|---|
| `SimpleAgent` | Single-turn | No tools, lightweight chat |
| `OrchestratorAgent` | Multi-turn | Tool-calling loop; two modes: OpenAI function_calling or structured THOUGHT/TOOL/INPUT/FINAL_ANSWER |
| `NativeReActAgent` | Multi-turn | Thought-Action-Observation loop |
| `NativeOpenHandsAgent` | Multi-turn | CodeAct — generates and executes Python |
| `OperativeAgent` | Persistent | Stateful, scheduled, with memory |
| `MonitorOperativeAgent` | Long-horizon | Configurable strategy axes |
| `morning_digest` | Scheduled | Email + calendar + news → TTS briefing |
| `deep_research` | On-demand | Multi-hop research with citations |
| `ClaudeCodeAgent` | On-demand | Claude SDK via Node.js subprocess |
| `SandboxedAgent` | Wrapper | Runs any agent inside Docker/Podman |

---

### Primitive 4 — Tools & Memory (`tools/`, `memory/`, `channels/`, `connectors/`)

**Tools (20+)**: `calculator`, `code_interpreter`, `web_search`, `file_read/write`, `shell_exec`, `http_request`, `retrieval`, `mcp_adapter`, `browser`, `git_tool`, `pdf_tool`, `image_tool`, and more. Tools implement `BaseTool.execute()` and are registered in the `ToolRegistry`.

**Memory (5 backends)**:

| Backend | Details |
|---|---|
| SQLite/FTS5 | Default, zero-dependency |
| FAISS | Dense vector retrieval |
| ColBERTv2 | Late interaction |
| BM25 | Classic term-frequency |
| Hybrid RRF | Sparse + dense fusion |

When `context_from_memory = true`, relevant docs are retrieved and prepended to the prompt with source attribution.

**Channels (30+)**: Messaging platform adapters — Telegram, Discord, Slack, WhatsApp, iMessage, Teams, Signal, Matrix, Twitter, Reddit, Twitch, IRC, Zulip, email, and more. All implement `BaseChannel` with `connect/send/receive/disconnect`. Incoming messages route through a `channel_bridge` to the configured agent.

**Connectors**: Data source adapters for Gmail, Google Calendar/Drive, Notion, Apple Health/Notes/Music/Contacts, Oura, Strava, Obsidian, Spotify, Dropbox, GitHub Notifications, Hacker News, RSS, weather, and more.

**MCP (Model Context Protocol)**: Full client/server implementation with stdio, SSE, and in-process transports — allowing agents to use external MCP tool servers.

**A2A (Agent-to-Agent)**: Google A2A protocol for inter-agent RPC.

---

### Primitive 5 — Learning (`learning/`, `traces/`, `telemetry/`)

Every interaction produces a **`Trace`** capturing the full step sequence (routing, memory retrieval, inference, tool calls, final response).

The `LearningOrchestrator` runs an 8-step cycle:

1. Mine traces for SFT / routing / agent training pairs
2. Baseline evaluation
3. Update routing recommendations (heuristic → learned → GRPO)
4. Evolve agent configs (via `AgentConfigEvolver`)
5. Run LoRA/SFT training (if torch available)
6. Post-learning eval
7. Accept/reject on `min_improvement` threshold
8. Apply or discard changes

**Optimization weights**: accuracy 60%, latency 20%, cost 10%, energy efficiency 10%.

The `distillation` subsystem adds a frontier-driven loop (M1→M2→M3 spec-level pipeline) that uses larger "teacher" models to improve local "student" models.

**Telemetry** samples energy at 50ms intervals across NVIDIA (NVML), AMD (amdsmi/RAPL), and Apple Silicon (`powermetrics`).

---

### API Server (`server/`)

FastAPI app exposing an **OpenAI-compatible HTTP API**:

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | Chat with streaming, memory injection, complexity analysis, agent routing |
| `GET /v1/models` | List available models |
| `GET /health` | Health check |
| WebSocket bridge | Real-time token streaming to the frontend |
| Channel webhooks | Incoming messages from messaging platforms |
| Telemetry dashboard | Real-time metrics |
| File upload router | Document ingestion |

Includes auth middleware, per-user session store, and cost/savings calculators.

---

### Rust Extension (`rust/`)

17 Rust crates compiled to a PyO3 Python extension (`openjarvis_rust`), covering the performance-critical paths:

| Crate | Purpose |
|---|---|
| `openjarvis-core` | Shared types (Message, ToolCall, Role, Quantization) |
| `openjarvis-engine` | Inference engine trait + Tokio async |
| `openjarvis-agents` | Agent execution loop in Rust |
| `openjarvis-tools` | Tool registry + executor |
| `openjarvis-learning` | Training data mining, optimization |
| `openjarvis-telemetry` | GPU metrics collection |
| `openjarvis-traces` | Trace storage and indexing |
| `openjarvis-security` | ED25519 signing, secure operations |
| `openjarvis-mcp` | MCP protocol implementation |
| `openjarvis-sessions` | Session storage (RwLock-based) |
| `openjarvis-workflow` | Workflow graph execution |
| `openjarvis-skills` | Skill index + executor |
| `openjarvis-scheduler` | Task scheduling (Tokio-based) |
| `openjarvis-a2a` | Agent-to-Agent RPC |

---

### CLI (`jarvis`)

40+ Click commands including:

```
jarvis init          # auto-detect hardware, recommend engine + model
jarvis doctor        # verify setup and diagnose issues
jarvis ask           # single query
jarvis chat          # interactive multi-turn chat
jarvis serve         # start the FastAPI server
jarvis digest        # run morning digest
jarvis bench         # benchmark latency / throughput / energy
jarvis skill install # install skills from Hermes / OpenClaw / GitHub
jarvis memory index  # index documents into the knowledge base
jarvis connect       # OAuth flow for connectors (Gmail, GDrive, etc.)
jarvis optimize      # run the learning loop
jarvis agent list    # manage running agents
jarvis workflow      # define and run multi-step workflows
```

---

## How It All Connects

```
User (CLI / Browser / Desktop / Channel)
         │
         ▼
   FastAPI Server  ──── WebSocket streaming ──→  Frontend
         │
         ▼
   Learning Router (picks model + agent based on trace history)
         │
    ┌────┴──────────────────┐
    ▼                       ▼
  Agent (Orchestrator,    Memory (retrieve
  ReAct, Operative…)      relevant context)
    │
    ├── Tool calls ─→ Tools (shell, web, code, MCP…)
    ├── Inference   ─→ Engine (Ollama, vLLM, Cloud…)
    └── Channels    ─→ WhatsApp, Telegram, Slack…
         │
         ▼
    Trace recorded → Learning loop → Improves routing,
                                     agent config, & model
```

The feedback loop is the key differentiator: **agents produce traces → traces inform learning → learning improves routing → better routing improves agents**.

┌─────────────────────────────────┐
│   React frontend (browser/Tauri) │  TypeScript/TSX
│   Chat, Dashboard, Settings UI  │
└──────────────┬──────────────────┘
               │ HTTP / SSE (REST API)
               │ Tauri invoke() when desktop
┌──────────────▼──────────────────┐
│   Python FastAPI server          │  Python
│   CLI, Agents, Tools, Config     │
│   Speech, Connectors, Training   │
└──────────────┬──────────────────┘
               │ import openjarvis_rust (PyO3)
┌──────────────▼──────────────────┐
│   Rust native extension          │  Rust (rust/)
│   Security, Memory, Telemetry    │
│   Agent runtime, ML policies     │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│   Tauri desktop shell            │  Rust (desktop/src-tauri/)
│   Native window, overlay UI      │
│   Bridges frontend ↔ Python server│
└─────────────────────────────────┘

---

## Quick Start

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync
uv sync --extra server

jarvis init          # hardware detection + setup
jarvis doctor        # verify everything is healthy
jarvis ask "What is the capital of France?"
```

## Starter Presets

```bash
jarvis init --preset morning-digest-mac    # Daily spoken briefing
jarvis init --preset deep-research         # Multi-hop research assistant
jarvis init --preset code-assistant        # Code execution + file I/O
jarvis init --preset scheduled-monitor     # Persistent stateful agent
jarvis init --preset chat-simple           # Lightweight conversation
```

                                        Registered Tools                                         
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Name                    ┃ Description                                       ┃ Category        ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ apply_patch             │ Apply a unified diff patch to a file. Supports    │ filesystem      │
│                         │ standard unif                                     │                 │
│ audio_transcribe        │ Transcribe an audio file to text. Supports mp3,   │ media           │
│                         │ wav, m4a, og                                      │                 │
│ calculator              │ Evaluate a mathematical expression safely.        │ math            │
│                         │ Supports arithmet                                 │                 │
│ channel_list            │ List available messaging channels.                │ channel         │
│ channel_send            │ Send a message to a channel (Telegram, Discord,   │ channel         │
│                         │ Slack, etc.)                                      │                 │
│ channel_status          │ Check the connection status of the messaging      │ channel         │
│                         │ channel.                                          │                 │
│ code_interpreter        │ Execute Python code and return the output. Code   │ code            │
│                         │ runs in an i                                      │                 │
│ code_interpreter_docker │ Execute Python code in an isolated Docker         │ code            │
│                         │ container. Provide                                │                 │
│ db_query                │ Execute a SQL query against a SQLite or           │ database        │
│                         │ PostgreSQL database.                              │                 │
│ digest_collect          │ Fetch recent data from configured connectors      │ data            │
│                         │ (email, calenda                                   │                 │
│ file_read               │ Read the contents of a file. Returns the text     │ filesystem      │
│                         │ content.                                          │                 │
│ file_write              │ Write content to a file. Supports write and       │ filesystem      │
│                         │ append modes.                                     │                 │
│ git_commit              │ Stage files and create a git commit. Optionally   │ vcs             │
│                         │ stage specif                                      │                 │
│ git_diff                │ Show changes in the working tree or staging area. │ vcs             │
│                         │ Use staged                                        │                 │
│ git_log                 │ Show recent commit history of a git repository.   │ vcs             │
│                         │ Returns the                                       │                 │
│ git_status              │ Show the working tree status of a git repository. │ vcs             │
│                         │ Returns po                                        │                 │
│ http_request            │ Make an HTTP request to a URL. Supports GET,      │ network         │
│                         │ POST, PUT, DELE                                   │                 │
│ image_generate          │ Generate an image from a text description.        │ media           │
│                         │ Returns the image                                 │                 │
│ kg_add_entity           │ Add an entity to the knowledge graph.             │ knowledge_graph │
│ kg_add_relation         │ Add a relation between two entities in the        │ knowledge_graph │
│                         │ knowledge graph.                                  │                 │
│ kg_neighbors            │ Find entities connected to a given entity.        │ knowledge_graph │
│ kg_query                │ Query the knowledge graph by entity or relation   │ knowledge_graph │
│                         │ type.                                             │                 │
│ llm                     │ Send a prompt to a language model. Useful for     │ inference       │
│                         │ sub-queries or                                    │                 │
│ memory_index            │ Index a file or directory into the memory         │ storage         │
│                         │ backend.                                          │                 │
│ memory_manage           │ Read, add, update, or remove entries in           │ memory          │
│                         │ persistent agent mem                              │                 │
│ memory_retrieve         │ Retrieve relevant content from the memory         │ storage         │
│                         │ backend.                                          │                 │
│ memory_search           │ Search memory for content relevant to a query.    │ storage         │
│                         │ Returns resul                                     │                 │
│ memory_store            │ Store content in the memory backend for later     │ storage         │
│                         │ retrieval.                                        │                 │
│ pdf_extract             │ Extract text from a PDF file. Returns the         │ media           │
│                         │ extracted text con                                │                 │
│ repl                    │ Execute Python code in a persistent REPL session. │ code            │
│                         │ Variables,                                        │                 │
│ retrieval               │ Search the knowledge base for relevant            │ memory          │
│                         │ information. Returns                              │                 │
│ shell_exec              │ Execute a shell command and return its            │ system          │
│                         │ stdout/stderr. Runs w                             │                 │
│ skill_manage            │ Create, list, load, or delete agent-authored      │ skill           │
│                         │ skills.                                           │                 │
│ text_to_speech          │ Convert text to spoken audio. Returns the file    │ audio           │
│                         │ path to the g                                     │                 │
│ think                   │ A reasoning scratchpad. Think through a problem   │ reasoning       │
│                         │ step by step                                      │                 │
│ user_profile_manage     │ Read, add, update, or remove entries in user      │ memory          │
│                         │ profile.                                          │                 │
│ web_search              │ Search the web for current information. Returns   │ search          │
│                         │ relevant sea                                      │                 │
└─────────────────────────┴───────────────────────────────────────────────────┴─────────────────┘

uv run jarvis ask "What is the capital of France?"
jarvis ask "query"
    │
    ├─ load_config()
    ├─ score_complexity(query)         ← auto-sizes max_tokens
    ├─ get_engine()                    ← finds Ollama/vLLM/etc
    ├─ setup_security()                ← guardrails wrapper
    ├─ InstrumentedEngine()            ← telemetry wrapper
    │
    ├─ [--agent flag?]
    │      YES → OrchestratorAgent.run()
    │                └─ tool-calling loop → engine.generate() × N
    │      NO  → engine.generate() × 1  (direct)
    │
    ├─ print(result.content)
    └─ save telemetry → .openJarvis/db/telemetry.db