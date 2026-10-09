.PHONY: up down migrate seed test demo-reset lint-imports

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

demo-reset:
	docker compose down -v
	docker compose up --build -d
	@echo "Waiting for DB..."
	@sleep 5
	$(MAKE) migrate
	$(MAKE) seed
	@echo "Demo reset complete."

lint-imports:
	docker compose exec api lint-imports
