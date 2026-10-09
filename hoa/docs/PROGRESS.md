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

---

## Task 2 — Seed Pipeline and Data Ingestion
**Status**: ✅ COMPLETE

### Built
- CSV & Excel parser converting raw dataset (`Acentra_Knowledge_Base_Source.xlsx`, `Roles`, `Policy_Thresholds`, `Routing_Rules`) into knowledge nodes, edges, chunks, and database seeds.
- Seed script (`make seed`) inserting demo users, active graph version, node chunks with tsvector full-text search and embeddings, policy thresholds, and routing rules.

---

## Task 3 — Authentication and RBAC
**Status**: ✅ COMPLETE

### Built
- Argon2 password hashing (`pwd_context`).
- JWT Access Token (15-min TTL) & Refresh Token; claims: `sub`, `app_role`, `active_dept_role`, `shift_exp`.
- Endpoints: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/persona`, `GET /auth/me`.
- Server-side permission map (`require_perm`) enforcing `app_role` boundaries:
  - `employee`: `chat:use`, `feedback:write`
  - `agent`: + `tickets:read`, `tickets:update`
  - `admin`: + `analytics:read`, `audit:read`, `audit:verify`, `knowledge:read`, `knowledge:write`, `users:manage`, `system:manage`
- Seed users created (password `Demo@1234`): one employee per dept role, dual-hat user, `agent@demo`, `admin@demo`.

---

## Task 4 — Knowledge Retrieval & Confidence Scoring
**Status**: ✅ COMPLETE

### Built
- Hybrid retrieval: Vector top-20 (exact cosine) + Postgres Full-Text top-20 (`websearch_to_tsquery` + `ts_rank`).
- Reciprocal Rank Fusion (RRF, $k=60$) selecting top 5 entry nodes.
- Graph expansion in NetworkX (hydrated per active graph version): 1-2 hops over allowed structural/approved origin edges with inverse-degree weighting (max 15 nodes), verifying status/visibility on every hop.
- Superseded node handling: detects superseded entry nodes and flags `supersedes`.
- Confidence scoring: weighted average of top-1 cosine, node completeness, and graph density, classified into `HIGH` (>=0.75), `MEDIUM` (0.50-0.74), `LOW` (<0.50).
- Evidence bundle generation with conflict detection and owner extraction.

---

## Task 5 — LLM Gateway, Input Guard & Intent Understanding
**Status**: ✅ COMPLETE

### Built
- `LLMPort` with `MistralAdapter` (httpx.AsyncClient to Mistral AI API, retries on 429/5xx, circuit breaker opening on 5 failures for 30s) and `TemplateAdapter` fallback.
- `Guard`: Clinical safety lexicon + regex detection (dosage, diagnosis, clinical advice, disguised phrasings), prompt injection detection, and off-topic filtering. Fails closed (refuses unsafe input).
- `Intent`: Multi-class intent understanding (information query, guided workflow, account-specific, sensitive report, complaint, clinical, unclear).

---

## Task 6 — Orchestrator Pipeline & Chat Endpoint
**Status**: ✅ COMPLETE

### Built
- Orchestrator pipeline executing: Guard → Understand → Retrieve → Verify → Decide → Generate → Record.
- Deterministic decision table covering all branches (Guard refusal, evidence conflict, low confidence, sensitive reports, workflows, direct answers) with 100% unit test branch coverage (`tests/test_decide.py`).
- Citation enforcement: `[ART-###]` format linking to node metadata.
- `POST /chat` endpoint returning structured response with answer, confidence band, citations, stage latencies, and workflow state.

---

## Task 7 — Guided Workflows, Routing & Tickets
**Status**: ✅ COMPLETE

### Built
- FSM generator (`app/workflow/fsm.py`) driving slot collection, field validation (types, allowed values, regex), and threshold/approval checks.
- Encrypted Postgres session store (`app/workflow/session_store.py`) with Fernet encryption (`VAULT_KEY`) for sensitive fields (`mrn`, `ssn`, `dob`), 30-min TTL, and version drift checks.
- Guided workflow scenarios:
  - **MRI Pre-Authorization**: Slot collection (insurer, procedure_code, scheduled_date, authorization_status, patient_mrn), pre-auth requirement checking, pending status instructions, and rejected status routing to `Insurance/TPA`.
  - **Discharge Billing Clearance**: Balance threshold check (> $5,000 routes to `Billing Supervisor`).
  - **Specimen Rejection & Resubmission**: Chain-of-custody logging and resubmission routing to `Laboratory`.
- Ticketing API (`app/ticketing/api.py`):
  - Idempotency key deduplication (60-min window within same encounter).
  - Separation of duties (creator cannot claim or resolve their own ticket).
  - Full audit trail (`ticket_events`).
- Deterministic routing engine (`app/ticketing/routing.py`): always-routed intents list + DB-backed `routing_rules` mapping.
- Full Console / Tickets endpoints (`GET /console/tickets`, `POST /console/tickets/{id}/claim`, `POST /console/tickets/{id}/reassign`, `POST /console/tickets/{id}/resolve`, `GET /console/tickets/{id}/events`).
- Unit test suite (`tests/test_workflow_ticketing.py`) covering all Task 7 components.

---

## Task 8 — Audit Log, Analytics, System Settings & Admin Console APIs
**Status**: ✅ COMPLETE

### Built
- Audit log HMAC SHA-256 chain generator & integrity verifier (`app/audit/api.py`): `GET /audit/log` & `GET /audit/verify`.
- Real-time Analytics Engine (`app/analytics/api.py`): `GET /analytics/summary` aggregating interaction metrics, outcome distributions, confidence bands, gap rates, ticket volume by team, and stage latencies.
- Database-backed System Settings (`app/core/system_settings.py`): `GET /admin/settings` & `POST /admin/settings` with emergency LLM kill switch (`llm_enabled`), confidence threshold overrides, and circuit breaker status.
- User Feedback API (`app/feedback/api.py`): `POST /feedback` storing thumbs up/down ratings and comments.
- Admin Knowledge Management (`app/knowledge/admin.py`): `GET /admin/knowledge/articles`, `POST /admin/knowledge/articles`, `POST /admin/knowledge/publish` (version graph activation), and `POST /admin/knowledge/rollback`.
- Unit test suite (`tests/test_admin_analytics_audit.py`).

---

## Task 9 — Frontend User Interfaces
**Status**: ✅ COMPLETE

### Built
- **Healthcare Operations Chat Console** (`src/pages/ChatPage.tsx`):
  - Interactive chat interface with real-time response streaming.
  - In-line interactive slot-filling form for guided workflow steps (`COLLECT` / `GUIDE` states).
  - Confidence badges (`HIGH`, `MEDIUM`, `LOW`), mode badges (`LLM`, `TEMPLATE`), citation badges (`[ART-###]`), and latency accordion dropdowns.
  - Message feedback buttons (thumbs up / thumbs down).
  - Persona switcher & session reset controls.
- **Admin Console & Governance Hub** (`src/pages/AdminPage.tsx`):
  - **Dashboard**: KPI cards (Total Interactions, Gap Rate, High Confidence %, Avg Latency) and live audit log stream.
  - **Tickets Console**: Urgency badges, team/status filtering, and claim/reassign/resolve detail modal.
  - **Knowledge Management**: Article search/catalog, Create Article dialog, Publish Graph Version, and Rollback graph version.
  - **Analytics View**: Recharts visual bar charts for decision outcomes, confidence distributions, and pipeline stage latencies.
  - **Audit Verification View**: HMAC SHA-256 cryptographic chain verification runner.
  - **User Management**: User directory with app role badges and active department roles.
  - **System Controls**: Emergency LLM provider kill switch toggle and threshold configuration.
- **Production Build**: Successfully compiled via Vite (`npm run build`).

---

## Task 10 — Evaluation & Benchmarking Suite
**Status**: ✅ COMPLETE

### Built
- Evaluation Runner (`app/eval/api.py`):
  - Baseline evaluation cases (`seed` split) covering safety refusals, guided workflows, policy queries, and always-routed queries.
  - Benchmarks pipeline performance against expected metrics: Intent accuracy, Outcome correctness, Citation recall, Safety refusal rate, and Latency (avg, p50, p95).
  - Persists `EvalRun` and `EvalResult` records in DB.
  - Admin endpoint `POST /admin/eval/run`.
- Unit test suite (`tests/test_eval.py`).
