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

## Demo Accounts

> **All passwords:** `Demo@1234`

### Application Roles

| Email | App Role | Notes |
|---|---|---|
| `admin@demo` | **admin** | Full access |
| `agent@demo` | **agent** | Tickets + chat |
| `frontoffice@demo` | employee | Front Office dept |
| `admission@demo` | employee | Admission dept |
| `discharge@demo` | employee | Discharge dept |
| `billing@demo` | employee | Billing dept |
| `billing.super@demo` | employee | **Dual-hat**: Billing + Billing Supervisor |
| `insurance@demo` | employee | Insurance/TPA dept |
| `itsupport@demo` | employee | IT Support dept |
| `lab@demo` | employee | Lab dept |
| `radiology@demo` | employee | Radiology dept |
| `quality@demo` | employee | Quality dept |
| `opsmanager@demo` | employee | Operations Manager dept |

### Persona Switching

Users with multiple dept roles (e.g. `billing.super@demo`) can switch their active role via `POST /auth/persona`. The new token carries the switched `active_dept_role`, which gates knowledge-graph retrieval.

### Permission Map

| Permission | employee | agent | admin |
|---|---|---|---|
| `chat:use` | ✅ | ✅ | ✅ |
| `feedback:write` | ✅ | ✅ | ✅ |
| `tickets:read` | ❌ | ✅ | ✅ |
| `tickets:update` | ❌ | ✅ | ✅ |
| `analytics:read` | ❌ | ❌ | ✅ |
| `audit:read` | ❌ | ❌ | ✅ |
| `audit:verify` | ❌ | ❌ | ✅ |
| `knowledge:read` | ❌ | ❌ | ✅ |
| `knowledge:write` | ❌ | ❌ | ✅ |
| `users:manage` | ❌ | ❌ | ✅ |
| `system:manage` | ❌ | ❌ | ✅ |
