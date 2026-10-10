.PHONY: install run run-gateway run-echo test lint fmt sync

# ── Setup ────────────────────────────────────────────────────────

install: sync

sync:
	uv sync --extra dev

# ── Run ──────────────────────────────────────────────────────────

run:
	@echo "Starting Gateway (HTTP) + Echo worker (Ctrl+C to stop both)"
	@trap 'kill 0' EXIT; \
	uv run python -m gateway & \
	uv run python -m examples.echo.worker & \
	wait

run-gateway:
	uv run python -m gateway

run-echo:
	uv run python -m examples.echo.worker

# ── Dev ──────────────────────────────────────────────────────────

test:
	uv run pytest tests/ -q

test-v:
	uv run pytest tests/ -v

lint:
	uv run ruff check gateway/ tests/ examples/ sdk/

fmt:
	uv run ruff format gateway/ tests/ examples/ sdk/

# ── Docker Compose ───────────────────────────────────────────────

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

restart:
	docker compose restart

build:
	docker compose build
