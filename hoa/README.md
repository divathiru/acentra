# Healthcare Operations Assistant (HOA)

Hospital operations staff chat with an AI assistant that answers operational questions with source citations, guides routine workflows, and routes anything needing human judgment to the right team.

## Quick Start

```bash
cp .env.example .env
# Edit .env with real secrets / keys
make up          # Start all services
make migrate     # Run database migrations
make seed        # Load synthetic seed data
```

## Services

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:5173 | React SPA (chat + admin) |
| API | http://localhost:8000 | FastAPI backend |
| DB | localhost:5432 | PostgreSQL 16 + pgvector |

## Development

```bash
make test        # Run backend tests
make lint-imports # Check module boundary rules
make demo-reset  # Wipe & re-seed everything
```

## Architecture

Modular monolith. Backend modules communicate only through each module's `api.py`.

Pipeline: **Guard → Understand → Retrieve → Verify → Decide → Generate → Record**

Every message ends in exactly one outcome: `ANSWER`, `GUIDE`, `ROUTE`, or `REFUSE`.
