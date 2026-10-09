"""Healthcare Operations Assistant — FastAPI entry point."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import TokenClaims, require_perm
from app.core.logging import setup_logging
from app.core.auth_router import router as auth_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    setup_logging()
    log = structlog.get_logger()
    log.info("hoa.startup")
    yield
    log.info("hoa.shutdown")


app = FastAPI(
    title="Healthcare Operations Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request-ID middleware ──
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=req_id)
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# ── Health endpoints ──
@app.get("/livez", tags=["health"])
def livez():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz():
    """Checks DB connectivity and whether an active graph version exists."""
    checks: dict = {}
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["db"] = "ok"
        finally:
            db.close()
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        return {"status": "not_ready", "checks": checks}

    try:
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT id FROM graph_versions WHERE status = 'active' LIMIT 1")
            ).fetchone()
            checks["active_graph"] = "ok" if row else "no active graph version"
        finally:
            db.close()
    except Exception:
        checks["active_graph"] = "table not found (run migrations)"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "not_ready"
    return {"status": overall, "checks": checks}


# ── Auth ──
app.include_router(auth_router)


# ── Admin-only stub routers (for RBAC tests) ──────────────────────────────────

from fastapi import APIRouter

_analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

@_analytics_router.get("/summary")
def analytics_summary(claims: Annotated[TokenClaims, Depends(require_perm("analytics:read"))]):
    return {"status": "ok", "role": claims.app_role}

app.include_router(_analytics_router)


_users_router = APIRouter(prefix="/users", tags=["users"])

@_users_router.get("")
def list_users(claims: Annotated[TokenClaims, Depends(require_perm("users:manage"))]):
    return {"status": "ok", "role": claims.app_role}

app.include_router(_users_router)


_audit_router = APIRouter(prefix="/audit", tags=["audit"])

@_audit_router.get("/log")
def audit_log(claims: Annotated[TokenClaims, Depends(require_perm("audit:read"))]):
    return {"status": "ok", "role": claims.app_role}

@_audit_router.post("/verify")
def audit_verify(claims: Annotated[TokenClaims, Depends(require_perm("audit:verify"))]):
    from app.audit.api import verify_chain
    from app.core.deps import get_db
    db = next(get_db())
    ok, violations = verify_chain(db)
    return {"chain_valid": ok, "violations": violations}

app.include_router(_audit_router)


_tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])

@_tickets_router.get("")
def list_tickets(claims: Annotated[TokenClaims, Depends(require_perm("tickets:read"))]):
    return {"status": "ok", "role": claims.app_role}

app.include_router(_tickets_router)
