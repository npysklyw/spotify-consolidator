.PHONY: setup test lint typecheck check dev frontend migration migrate
setup:
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -e './backend[dev]'
	cd frontend && npm ci

test:
	cd backend && .venv/bin/pytest
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint

typecheck:
	cd backend && .venv/bin/mypy
	cd frontend && npm run typecheck

check: test lint typecheck
	cd frontend && npm run build

dev:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1

frontend:
	cd frontend && npm run dev

migrate:
	cd backend && .venv/bin/alembic upgrade head

migration:
	@test -n "$(name)" || (echo 'Usage: make migration name="describe the schema change"' && exit 1)
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(name)"
