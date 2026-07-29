.PHONY: up down logs api-shell migrate seed test test-idor lint frontend-install frontend-dev trust-ca content-gate restore-drill

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f proxy api web db

api-shell:
	docker compose run --rm api sh

migrate:
	docker compose run --rm api alembic -c backend/alembic.ini upgrade head

seed:
	docker compose run --rm api python -m app.seed

test:
	docker compose run --rm api pytest

test-idor:
	docker compose run --rm api pytest -m idor

lint:
	docker compose run --rm api ruff check backend
	docker compose run --rm api mypy

frontend-install:
	cd frontend && npm ci

frontend-dev:
	cd frontend && npm run dev

trust-ca:
	powershell -ExecutionPolicy Bypass -File infra/caddy/trust-root.ps1

content-gate:
	TRAINER_CONTENT_GATE_STRICT=1 python scripts/check_content_gate.py

restore-drill:
	bash infra/restore/restore_drill.sh
