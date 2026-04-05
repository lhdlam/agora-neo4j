.DEFAULT_GOAL := help

# ── Load .env if present ───────────────────────────────────────
# -include (dash) suppresses the error when .env does not exist
# (e.g. CI/ECS where secrets come from the environment directly).
# export (bare) forwards every Make variable to child process shells,
# so docker compose, pytest, mypy, etc. all see the same env vars.
-include .env
export

# ── Virtual-env path (bin on Unix/Mac, Scripts on Windows) ────
ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
else
  VENV_BIN := .venv/bin
endif

PYTHON    := $(VENV_BIN)/python
PIP       := $(VENV_BIN)/pip
RUFF      := $(VENV_BIN)/ruff
MYPY      := $(VENV_BIN)/mypy
PYTEST    := $(VENV_BIN)/pytest
PRECOMMIT := $(VENV_BIN)/pre-commit
DC        := docker compose

# ──────────────────────────────────────────────────────────────
.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(firstword $(MAKEFILE_LIST)) \
		| awk 'BEGIN {FS=":.*##"}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ──────────────────────────────────────────────────────────────
# Auto-detect all docker-compose.*.yml files in infrastructure/
# Adding a new compose file there is enough — no Makefile change needed.
COMPOSE_FILES := $(sort $(wildcard infrastructure/docker-compose.*.yml))
COMPOSE_ARGS  := $(foreach f,$(COMPOSE_FILES),-f $(f))

ifeq ($(COMPOSE_FILES),)
  $(error No docker-compose.*.yml files found in infrastructure/)
endif

# Docker subcommand dispatcher
# Usage:  make docker <subcommand>
#	make docker build	- build all images
#   make docker up      — start all services
#   make docker down    — stop (volumes preserved)
#   make docker purge   — stop + delete all volumes  ⚠️
#   make docker logs    — tail logs
#   make docker ps      — show running containers
#   make docker ai-model-volume - pre-load AI model into external volume

_DOCKER_VALID_CMDS := build up down purge logs ps restart ai-model-volume
_DOCKER_SUB        := $(filter $(_DOCKER_VALID_CMDS), $(MAKECMDGOALS))

# Default to up if no subcommand is specified
ifeq ($(_DOCKER_SUB),)
	_DOCKER_SUB := up
endif

# Absorb the subcommand word(s) so Make doesn't error "no rule for target"
$(foreach c,$(_DOCKER_VALID_CMDS),$(eval $(c): ;@:))

.PHONY: docker
docker:  ## Infrastructure: make docker <build|up|down|purge|logs|ps|restart|ai-model-volume>
	$(if $(_DOCKER_SUB),,@echo "Usage: make docker <build|up|down|purge|logs|ps|restart|ai-model-volume>" && exit 1)
	@$(MAKE) --no-print-directory _docker-$(_DOCKER_SUB)

# ── Internal docker targets (not shown in help) ───────────────
.PHONY: _docker-build
_docker-build:
	$(DC) $(COMPOSE_ARGS) build $(opts)
	@echo "✅  All infrastructure built."

.PHONY: _docker-restart
_docker-restart:
	$(DC) $(COMPOSE_ARGS) restart $(svc)
	@echo "✅  All infrastructure restarted."

.PHONY: _docker-up
_docker-up:
	$(DC) $(COMPOSE_ARGS) up -d
	@echo "✅  All infrastructure started."

.PHONY: _docker-down
_docker-down:
	$(DC) $(COMPOSE_ARGS) down
	@echo "✅  All infrastructure stopped."

.PHONY: _docker-purge
_docker-purge:
	@echo "⚠️   This will permanently delete all Docker volumes (ES data, Kafka, Grafana...)."
	@printf "Continue? [y/N] "; read ans; [ "$${ans:-N}" = y ] || [ "$${ans:-N}" = Y ] || (echo "Aborted."; exit 1)
	$(DC) $(COMPOSE_ARGS) down -v
	@echo "✅  All infrastructure stopped and volumes removed."

.PHONY: _docker-logs
_docker-logs:
	$(DC) $(COMPOSE_ARGS) logs -f $(svc)

.PHONY: _docker-ps
_docker-ps:
	$(DC) $(COMPOSE_ARGS) ps

# ──────────────────────────────────────────────────────────────
.PHONY: _docker-ai-model-volume
_docker-ai-model-volume:  ## Pre-load AI model into external volume
	docker volume create agora-model-cache 2>/dev/null || true
	$(DC) $(COMPOSE_ARGS) run --rm -u root worker python -c "from fastembed import TextEmbedding; import os; TextEmbedding(model_name=os.environ.get('EMBEDDING_MODEL'))"
	@echo "✅  Model pre-loaded into agora-model-cache volume."


# ──────────────────────────────────────────────────────────────
.PHONY: install
install:  ## Install all dependencies (prod + dev) into .venv
	$(PIP) install -e ".[dev]"
	$(PRECOMMIT) install
	@echo "✅  Dependencies installed and pre-commit hooks registered."

.PHONY: uninstall
uninstall:  ## Uninstall ALL packages in .venv + deregister pre-commit hooks
	$(PRECOMMIT) uninstall 2>/dev/null || true
	$(PIP) freeze --exclude-editable | xargs $(PIP) uninstall -y 2>/dev/null || true
	$(PIP) uninstall -y agora-market 2>/dev/null || true
	@echo "✅  All packages removed and pre-commit hooks deregistered."

# ──────────────────────────────────────────────────────────────
.PHONY: lint
lint:  ## Ruff linter — add fix=1 to auto-fix  (e.g. make lint fix=1)
	$(RUFF) check $(if $(fix),--fix) src/ src/tests/

.PHONY: format
format:  ## Ruff formatter — add check=1 for CI dry-run  (e.g. make format check=1)
	$(RUFF) format $(if $(check),--check) src/ src/tests/

# ──────────────────────────────────────────────────────────────
.PHONY: mypy
mypy:  ## Run mypy static type checking
	$(MYPY) src/

# ──────────────────────────────────────────────────────────────
.PHONY: test
test:  ## Run tests with coverage
	$(PYTEST) $(if $(cov),--cov=src --cov-report=term-missing)

# ──────────────────────────────────────────────────────────────
.PHONY: check
check:  ## Run all checks (CI pipeline)
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) mypy
	$(MAKE) test cov=1
	@echo ""
	@echo "✅  All checks passed."

# ──────────────────────────────────────────────────────────────
.PHONY: pre-commit
pre-commit:  ## Run pre-commit hooks on all files
	$(PRECOMMIT) run --all-files

# ──────────────────────────────────────────────────────────────
.PHONY: clean
clean:  ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.cypher" -delete 2>/dev/null || true
	@echo "✅  Cleaned."
