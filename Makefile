# ─── Environment ─────────────────────────────────────────────────────────────
# Reads ENVIRONMENT from .env file, falls back to dev.
# Override on the CLI: make up ENVIRONMENT=prod
# On the server .env contains ENVIRONMENT=prod so this auto-selects prod mode.
ENVIRONMENT   ?= $(or $(shell grep -s '^ENVIRONMENT=' .env | cut -d= -f2 | tr -d '[:space:]'),dev)
GMAPS_API_KEY ?= $(shell grep -s '^GMAPS_API_KEY=' .env | cut -d= -f2 | tr -d '[:space:]')
WORKER_API_KEY ?= $(shell grep -s '^WORKER_API_KEY=' .env | cut -d= -f2 | tr -d '[:space:]')

ifeq ($(ENVIRONMENT),prod)
  COMPOSE_FILES := -f docker-compose.yml -f docker-compose.prod.yml
else
  COMPOSE_FILES := -f docker-compose.yml
endif

COMPOSE := docker compose $(COMPOSE_FILES)

SERVER_HOST ?= root@156.155.250.65
SERVER_KEY  ?= ~/.ssh/hungu_rsa
SERVER_SSH  := ssh -i $(SERVER_KEY) $(SERVER_HOST)

.PHONY: up down restart logs ps build deploy server shell-api shell-worker

up:
	@echo "▶  Environment: $(ENVIRONMENT)"
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build --no-cache

## Pull latest code and redeploy — run ON the server for ad-hoc updates
deploy:
	git pull --ff-only
	$(COMPOSE) up -d --build --remove-orphans

## Run from local machine: stops local containers first, then redeploys on server.
## Prevents double API usage (local worker + server worker both calling AI keys).
server:
	@echo "▶  Stopping local containers..."
	docker compose -f docker-compose.yml down
	@echo "▶  Deploying to server $(SERVER_HOST)..."
	$(SERVER_SSH) "cd /opt/hungu && git pull --ff-only && sed -i 's|__GMAPS_API_KEY__|$(GMAPS_API_KEY)|g' services/web/index.html && sed -i 's|__WORKER_API_KEY__|$(WORKER_API_KEY)|g' services/web/index.html && sed -i 's|__WORKER_API_KEY__|$(WORKER_API_KEY)|g' services/web/admin.html && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans"
	@echo "✓  Server deploy complete. Local containers are down."

shell-api:
	$(COMPOSE) exec api bash

shell-worker:
	$(COMPOSE) exec worker bash

## Run ONCE after DNS A record points to the new server — gets SSL cert + restarts in prod mode
ssl:
	$(SERVER_SSH) "bash /opt/hungu/scripts/setup-ssl.sh"
