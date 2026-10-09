"""Healthcare Operations Assistant — FastAPI entry point."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import setup_logging


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
