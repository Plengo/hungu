# ─── Environment ─────────────────────────────────────────────────────────────
# Reads ENVIRONMENT from .env file, falls back to dev.
# Override on the CLI: make up ENVIRONMENT=prod
# On the server .env contains ENVIRONMENT=prod so this auto-selects prod mode.
ENVIRONMENT ?= $(or $(shell grep -s '^ENVIRONMENT=' .env | cut -d= -f2 | tr -d '[:space:]'),dev)

ifeq ($(ENVIRONMENT),prod)
  COMPOSE_FILES := -f docker-compose.yml -f docker-compose.prod.yml
else
  COMPOSE_FILES := -f docker-compose.yml
endif

COMPOSE := docker compose $(COMPOSE_FILES)

.PHONY: up down restart logs ps build deploy shell-api shell-worker

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

## Pull latest code and redeploy (use on server for ad-hoc updates)
deploy:
	git pull --ff-only
	$(COMPOSE) up -d --build --remove-orphans

shell-api:
	$(COMPOSE) exec api bash

shell-worker:
	$(COMPOSE) exec worker bash
