COMPOSE := docker compose -f docker-compose.mac.yml
URL     := http://localhost:8000

.PHONY: start stop restart build rebuild logs status health shell

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
	@curl -sf $(URL)/health | python3 -m json.tool 2>/dev/null || curl -sf $(URL)/health || echo "Jarvis is not responding"

## shell        – open a shell inside the container
shell:
	$(COMPOSE) exec jarvis bash

## help         – show this help
help:
	@grep '^## ' Makefile | sed 's/^## /  make /'
