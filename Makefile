COMPOSE := docker compose -f docker-compose.mac.yml
URL     := http://localhost:8000
API     := curl -sf $(URL)
FMT     := python3 -m json.tool 2>/dev/null

.PHONY: start stop restart build rebuild logs status health shell \
        info models agents sessions memory skills traces channels \
        connectors telemetry energy savings budget voice-health \
        security chat ollama-check check help

## start        – start Jarvis (existing image)
start:
	$(COMPOSE) up -d
	@echo "Jarvis started → $(URL)"

## stop         – stop Jarvis
stop:
	$(COMPOSE) down
	@echo "Jarvis stopped."

## restart      – restart the container
restart:
	$(COMPOSE) restart
	@echo "Jarvis restarted → $(URL)"

## build        – build image and start
build:
	$(COMPOSE) up -d --build
	@echo "Jarvis built and started → $(URL)"

## rebuild      – full rebuild (no cache) and start
rebuild:
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d
	@echo "Jarvis rebuilt and started → $(URL)"

## logs         – tail container logs (LINES=100)
logs:
	$(COMPOSE) logs -f --tail=$(or $(LINES),100)

## status       – show container status
status:
	$(COMPOSE) ps

## health       – quick health check
health:
	@$(API)/health | $(FMT) || echo "Jarvis is not responding"

## shell        – open a shell inside the container
shell:
	$(COMPOSE) exec jarvis bash

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

## ollama-check – verify Ollama is reachable from Docker
ollama-check:
	@echo "Host:" && curl -sf http://localhost:11434/api/tags | $(FMT) | head -5 || echo "  Ollama not running on host"; \
	 echo "Docker:" && $(COMPOSE) exec jarvis python3 -c \
	   "import urllib.request,json; r=urllib.request.urlopen('http://host.docker.internal:11434/api/tags'); d=json.loads(r.read()); print('  Models:', ', '.join(m['name'] for m in d['models']))" \
	   2>/dev/null || echo "  Cannot reach Ollama from container"

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
