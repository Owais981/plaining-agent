.PHONY: dev-backend dev-frontend seed migrate test lint up down

dev-backend:
	cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload

dev-frontend:
	cd frontend && npm run dev

migrate:
	cd backend && .venv/Scripts/python -m alembic upgrade head

seed:
	cd backend && .venv/Scripts/python scripts/seed.py

test:
	cd backend && .venv/Scripts/python -m pytest tests/ -q

lint:
	cd frontend && npm run lint

up:
	docker compose up --build

down:
	docker compose down
