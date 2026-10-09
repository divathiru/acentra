# Healthcare Operations Assistant (HOA)

Hospital operations staff chat with an AI assistant that answers operational questions with source citations, guides routine workflows, and routes anything needing human judgment to the right team.

## Architecture

The application is built as a modular monolith. Backend modules communicate via explicit `api.py` boundaries.

```mermaid
graph TD
    UI[Frontend (React/Vite)] --> API[FastAPI Backend]
    
    subgraph Backend
        API --> Pipeline
        
        subgraph Pipeline [Orchestrator Pipeline]
            G[Guard] --> U[Understand]
            U --> R[Retrieve]
            R --> V[Verify]
            V --> D[Decide]
            D --> Gen[Generate]
            Gen --> Rec[Record]
        end
        
        Pipeline --> DB[(PostgreSQL + pgvector)]
        Pipeline -.-> LLM((Mistral LLM))
    end
    
    subgraph Security & Audit
        Pipeline -.-> Audit[Audit Module (HMAC)]
        Audit --> DB
    end
```

Every message sent through the pipeline ends in exactly one of four outcomes: `ANSWER`, `GUIDE`, `ROUTE`, or `REFUSE`.

## Quick Start (5 Commands)

```bash
git clone <repo-url> && cd hoa
cp .env.example .env
make up          # Start all services (db, api, web)
make migrate     # Run database migrations
make seed        # Load synthetic seed data & initial knowledge graph
make demo-data   # Optional: load scripted interactions/tickets for demo
```

## Services & URLs

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:5173 | React SPA (chat + admin dashboards) |
| API | http://localhost:8000 | FastAPI backend |
| DB | localhost:5432 | PostgreSQL 16 + pgvector |

## Environment Variables (`.env`)

- **Database:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`
- **Security:** `JWT_SECRET` (auth signing), `AUDIT_HMAC_KEY` (tamper-proof logs), `VAULT_KEY` (Fernet encryption)
- **LLM:** `LLM_PROVIDER` (`mistral` or `template` for local fallback), `MISTRAL_API_KEY`
- **App:** `CORS_ORIGINS`, `LOG_LEVEL`

## Demo Accounts

> **All passwords:** `Demo@1234`

| Email | App Role | Notes |
|---|---|---|
| `admin@demo` | **admin** | Full access to Admin Dashboard (Analytics, Audit, Knowledge, etc.) |
| `agent@demo` | **agent** | Support agent (handles Tickets + chat) |
| `frontoffice@demo` | employee | Front Office department |
| `admission@demo` | employee | Admission department |
| `discharge@demo` | employee | Discharge department |
| `billing@demo` | employee | Billing department |
| `billing.super@demo` | employee | **Dual-hat**: Billing + Billing Supervisor |
| `insurance@demo` | employee | Insurance/TPA department |
| `lab@demo` | employee | Lab department |
| `radiology@demo` | employee | Radiology department |

Users with multiple dept roles (e.g., `billing.super@demo`) can switch active roles via the UI.

## Custom Knowledge Base

The system reads knowledge, workflows, and policies from an Excel workbook (`data/workbook.xlsx`). To swap in your own real workbook:

1. Place your Excel file in `data/`.
2. Edit `data/mapping.yaml` to map your sheet names and column headers to the HOA expected format.
3. Run `make seed` to ingest the new knowledge graph.

## Production Roadmap

For deploying HOA into a high-compliance production environment, we recommend the following AWS reference architecture:

- **Compute:** ECS Fargate (serverless containers, no OS patching).
- **Database:** Amazon RDS for PostgreSQL (multi-AZ, automated backups) with pgvector.
- **Rate Limiting / Sessions:** Amazon ElastiCache (Redis) to back `slowapi` and session state.
- **Security & Secrets:** AWS KMS for the `VAULT_KEY` and `AUDIT_HMAC_KEY`. AWS Secrets Manager for DB creds and API keys.
- **Immutability:** Send audit logs to an Amazon S3 bucket configured with **S3 Object Lock** (WORM compliance).
- **Network:** Deploy entirely within private subnets using VPC Endpoints to access AWS services securely.
