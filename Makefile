.PHONY: up down logs demo test test-backend test-frontend lint typecheck build audit openapi check-lf migration-check verify-compose

up:
	docker compose up --build --wait --wait-timeout 180

down:
	docker compose down

logs:
	docker compose logs --follow api worker web

demo:
	bash scripts/demo-cycle.sh

test: test-backend test-frontend

test-backend:
	cd services/api && uv run pytest

test-frontend:
	npm test

lint:
	cd services/api && uv run ruff check .
	npm run lint

typecheck:
	cd services/api && uv run mypy src
	npm run typecheck

build:
	npm run build

audit:
	npm run audit:high

openapi:
	cd services/api && uv run python -m promotion_control_plane.cli.main openapi --output ../../openapi/openapi.json
	npm run generate:types

check-lf:
	bash scripts/check-lf.sh

migration-check:
	cd services/api && bash ../../scripts/check-migration-drift.sh

verify-compose:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-compose.ps1
