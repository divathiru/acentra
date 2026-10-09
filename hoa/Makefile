.PHONY: up down migrate seed test eval demo-reset lint-imports

eval:
	docker compose exec api python -m app.eval.cli


up:
	docker compose up --build -d

down:
	docker compose down

migrate:
	docker compose exec -e PYTHONPATH=/app api alembic upgrade head

seed:
	docker compose exec api python -m app.seed

test:
	docker compose exec api python -m pytest tests/ -v

demo-data: demo-reset

demo-reset:
	docker compose exec api python -m app.demo_data

lint-imports:
	docker compose exec api lint-imports
