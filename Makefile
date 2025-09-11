SHELL := /bin/bash

.PHONY: help dev-install dev-install-service js-helpers test compile-service-reqs compile-dev-reqs token lint type format validate

help:
	@echo "Targets:"
	@echo "  dev-install            Install dev + test extras with uv"
	@echo "  dev-install-service    Install service + test extras with uv"
	@echo "  js-helpers             Install Node deps for Hardhat parser"
	@echo "  test                   Run test suite via pytest"
	@echo "                        Pass args with PYTEST_ARGS or ARGS, e.g.:"
	@echo "                        make test PYTEST_ARGS=\"-k unit -v\""
	@echo "  compile-service-reqs   Compile pinned requirements for service image (services/requirements.txt)"
	@echo "  compile-dev-reqs       Compile pinned dev/test requirements (requirements-dev.lock)"
	@echo "  token                  Generate HMAC token (set HMAC_SHARED_SECRET and REPO_URL)"
	@echo "  lint                   Run pylint"
	@echo "  type                   Run mypy"
	@echo "  format                 Run isort and black formatters"
	@echo "  validate               Run lint, type, and tests"

dev-install:
	uv pip install -e '.[dev,test]'

dev-install-service:
	uv pip install -e '.[service,test]'

js-helpers:
	@which node >/dev/null 2>&1 || { echo "Node.js not found in PATH"; exit 1; }
	@which npm >/dev/null 2>&1 || { echo "npm not found in PATH"; exit 1; }
	cd gardener/external_helpers/hardhat_config_parser && npm ci --omit=dev

test:
	pytest -q $(PYTEST_ARGS) $(ARGS)

compile-service-reqs:
	uv pip compile pyproject.toml -o services/requirements.txt --extra service

compile-dev-reqs:
	uv pip compile pyproject.toml -o requirements-dev.lock --extra dev --extra test

token:
	@if [ -z "$$HMAC_SHARED_SECRET" ]; then echo "Set HMAC_SHARED_SECRET env var"; exit 1; fi
	@if [ -z "$$REPO_URL" ]; then echo "Set REPO_URL env var"; exit 1; fi
	python services/scripts/gen_token.py --url "$$REPO_URL"

lint:
	uv run pylint gardener/ services/

type:
	uv run mypy gardener/ services/

format:
	uv run isort .
	uv run black .

validate: lint type test
