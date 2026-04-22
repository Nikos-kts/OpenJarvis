URL     := http://localhost:8000
API     := curl -sf $(URL)
FMT     := python3 -m json.tool 2>/dev/null
UV      := source $$HOME/.local/bin/env 2>/dev/null; uv

.PHONY: install build build-rust start debug stop restart logs status health \
        info models agents sessions memory skills traces channels \
        connectors telemetry energy savings budget voice-health \
        security chat ollama-check check help

## ── Setup ────────────────────────────────────────────────────

## install      – install Python + frontend deps + Rust extension locally
install:
	@echo "Installing Python deps..."
	$(UV) sync --extra server --extra inference-google --extra inference-cloud --extra memory-faiss --extra speech --extra scheduler --extra tools-search --extra dev
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@$(MAKE) build-rust
	@echo "Done."

## build-rust   – compile the Rust extension (openjarvis_rust) via maturin
build-rust:
	@command -v cargo >/dev/null 2>&1 || { echo "Error: Rust toolchain not found. Install from https://rustup.rs then re-run."; exit 1; }
	@echo "Installing maturin..."
	$(UV) pip install "maturin>=1.0,<2.0" -q
	@echo "Building Rust extension (first build may take a few minutes)..."
	export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1; $(UV) run maturin develop --release --manifest-path rust/crates/openjarvis-python/Cargo.toml
	@echo "Rust extension built successfully."

## build        – build frontend for production (into static/)
build:
	cd frontend && npm run build

## ── Run ──────────────────────────────────────────────────────

## start        – start backend + frontend (Ctrl+C to stop)
start:
	@echo "Starting OpenJarvis natively..."
	@(cd frontend && npm run dev) &
	$(UV) run jarvis serve --port 8000
	@echo "Stopped."

## debug        – start backend in DEBUG log level + frontend
debug:
	@echo "Starting OpenJarvis in debug mode..."
	@(cd frontend && npm run dev) &
	$(UV) run jarvis --verbose serve --port 8000
	@echo "Stopped."

## stop         – stop any running processes on ports 8000/5173
stop:
	@lsof -ti :8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti :5173 | xargs kill -9 2>/dev/null || true
	@echo "Stopped."

## restart      – stop then start
restart: stop
	@sleep 1
	@$(MAKE) start

## logs         – tail server logs (follow mode)
logs:
	@tail -f .openJarvis/cli.log 2>/dev/null || echo "No log file found — run 'make debug' first to generate logs"

## status       – show running Jarvis processes
status:
	@echo "Port 8000 (backend):" && lsof -ti :8000 2>/dev/null && echo "  running" || echo "  not running"; \
	 echo "Port 5173 (frontend):" && lsof -ti :5173 2>/dev/null && echo "  running" || echo "  not running"; \
	 echo "Ollama:" && lsof -ti :11434 2>/dev/null && echo "  running" || echo "  not running"

## health       – quick health check
health:
	@$(API)/health | $(FMT) || echo "Jarvis is not responding"

## ── Diagnostics ──────────────────────────────────────────────

## info         – server config (model, agent, engine)
info:
	@$(API)/v1/info | $(FMT)

## models       – list available models
models:
	@$(API)/v1/models | $(FMT)

## agents       – list registered & running agents
agents:
	@$(API)/v1/agents | $(FMT)

## sessions     – list recent sessions
sessions:
	@$(API)/v1/sessions | $(FMT)

## memory       – memory backend stats
memory:
	@echo "=== Stats ===" && $(API)/v1/memory/stats | $(FMT); \
	 echo "\n=== Config ===" && $(API)/v1/memory/config | $(FMT)

## skills       – list installed skills
skills:
	@$(API)/v1/skills | $(FMT)

## traces       – list recent execution traces
traces:
	@$(API)/v1/traces | $(FMT)

## channels     – messaging channels & bridge status
channels:
	@$(API)/v1/channels | $(FMT)

## connectors   – list connectors and connection status
connectors:
	@$(API)/v1/connectors | $(FMT)

## telemetry    – aggregated request/token/latency stats
telemetry:
	@$(API)/v1/telemetry/stats | $(FMT)

## energy       – energy monitoring stats
energy:
	@$(API)/v1/telemetry/energy | $(FMT)

## savings      – cost savings vs cloud providers
savings:
	@$(API)/v1/savings | $(FMT)

## budget       – current budget usage and limits
budget:
	@$(API)/v1/budget | $(FMT)

## voice-health – Gemini Live voice channel status
voice-health:
	@$(API)/v1/voice/live/health | $(FMT)

## security     – run security environment audit
security:
	@$(API)/v1/security/scan | $(FMT)

## ollama-check – verify Ollama is reachable
ollama-check:
	@curl -sf http://localhost:11434/api/tags | python3 -c \
	  "import sys,json; d=json.load(sys.stdin); print('Models:', ', '.join(m['name'] for m in d['models']))" \
	  2>/dev/null || echo "Ollama not running"

## check        – full system check (health + engine + models + agents)
check:
	@echo "── Health ──" && $(API)/health | $(FMT) || echo "  DOWN"; \
	 echo "\n── Info ──" && $(API)/v1/info | $(FMT) || echo "  unavailable"; \
	 echo "\n── Models ──" && $(API)/v1/models | $(FMT) || echo "  unavailable"; \
	 echo "\n── Agents ──" && $(API)/v1/agents | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Registered: {len(d.get(\"registered\",[]))}  Running: {len(d.get(\"running\",[]))}')" 2>/dev/null || echo "  unavailable"; \
	 echo "\n── Memory ──" && $(API)/v1/memory/stats | $(FMT) || echo "  unavailable"; \
	 echo "\n── Voice ──" && $(API)/v1/voice/live/health | $(FMT) || echo "  unavailable"; \
	 echo "\n── Ollama ──" && curl -sf http://localhost:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Models:', ', '.join(m['name'] for m in d['models']))" 2>/dev/null || echo "  not running"

## chat         – quick test chat (MSG="your message")
chat:
	@$(API)/v1/chat/completions -X POST -H 'Content-Type: application/json' \
	  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"$(or $(MSG),Say hello in one sentence)"}],"stream":false}' \
	  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])" 2>/dev/null \
	  || echo "Chat request failed"

## help         – show this help
help:
	@grep '^## ' Makefile | sed 's/^## /  make /'
