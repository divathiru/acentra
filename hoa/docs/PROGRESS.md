# Progress Log

## Task 1 — Scaffold monorepo and database
**Status**: ✅ COMPLETE

**Ports** (adjusted to avoid conflicts with other running projects on this machine):
| Service | Host port | Internal port |
|---------|-----------|---------------|
| DB (pgvector) | 5434 | 5432 |
| API (FastAPI) | 8001 | 8000 |
| Web (Vite) | 5175 | 5173 |

### Built
- **Monorepo structure**: `hoa/` with `backend/`, `frontend/`, `data/`, `docs/`
- **Backend**: FastAPI app with 9 module folders (guard, knowledge, orchestrator, workflow, ticketing, audit, llm, analytics, eval), each with `api.py` public interface
- **Config**: Single `Settings` Pydantic class in `core/config.py` — all env vars, no hardcoded secrets
- **Database models**: All tables defined in `core/models.py` (26 tables total)
- **Alembic migration**: `0001_baseline.py` creates all tables, enums, GIN index on `node_chunks.tsv`, and grants insert-only permissions on `audit_log` to `audit_writer` role
- **import-linter**: `.importlinter` config enforcing module boundaries
- **Health endpoints**: `GET /livez` (always ok), `GET /readyz` (checks DB + active graph version)
- **Middleware**: Request-ID (UUID per request), CORS, structlog JSON logging
- **Frontend**: Vite + React 18 + TypeScript + Tailwind scaffold with `/login`, `/chat`, `/admin` placeholder routes
- **Docker Compose**: db (pgvector/pgvector:pg16), api (Python 3.12), web (Node 20)
- **Makefile**: up, down, migrate, seed, test, demo-reset, lint-imports

### How to verify
```bash
cd hoa
cp .env.example .env
make up
make migrate
curl http://localhost:8000/livez      # → {"status":"ok"}
curl http://localhost:8000/readyz     # → {"status":"not_ready","checks":{"db":"ok","active_graph":"no active graph version"}}
# Frontend at http://localhost:5173
```

### Known gaps
- `/readyz` reports "no active graph version" — expected until seed data is loaded
- Frontend pages are placeholder stubs
- `make seed` is a no-op placeholder
- shadcn/ui components not yet initialized (will be done when building real UI)
