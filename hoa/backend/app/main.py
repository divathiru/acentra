"""Healthcare Operations Assistant — FastAPI entry point."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Optional

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import TokenClaims, require_perm, get_db
from app.core.logging import setup_logging
from app.core.auth_router import router as auth_router
from app.core.rate_limit import limiter


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

# ── Rate limiting ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — locked to env-configured origins only ──
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
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


# ── Chat endpoints ────────────────────────────────────────────────────────────

from fastapi import APIRouter

_chat_router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    workflow_slots: Optional[dict] = None
    required_fields: Optional[list] = None


@_chat_router.post("", response_model=None)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("chat:use"))],
    db: Annotated[object, Depends(get_db)],
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    from app.llm.api import get_llm
    from app.orchestrator.pipeline import run_pipeline

    llm = get_llm(db)
    resp, _ = await run_pipeline(
        query=body.query,
        user_id=claims.user_id,
        dept_role=claims.active_dept_role or "ALL",
        session=db,
        llm=llm,
        conversation_id=body.conversation_id,
        idempotency_key=idempotency_key,
        workflow_slots=body.workflow_slots,
        required_fields=body.required_fields,
    )
    return resp


@_chat_router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("chat:use"))],
    db: Annotated[object, Depends(get_db)],
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    from app.llm.api import get_llm
    from app.orchestrator.pipeline import stream_pipeline

    llm = get_llm(db)
    generator = stream_pipeline(
        query=body.query,
        user_id=claims.user_id,
        dept_role=claims.active_dept_role or "ALL",
        session=db,
        llm=llm,
        conversation_id=body.conversation_id,
        idempotency_key=idempotency_key,
        workflow_slots=body.workflow_slots,
        required_fields=body.required_fields,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


app.include_router(_chat_router)


# ── Admin-only stub routers ────────────────────────────────────────────────────

# ── Analytics Router ───────────────────────────────────────────────────────────

_analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@_analytics_router.get("/summary")
def analytics_summary(
    claims: Annotated[TokenClaims, Depends(require_perm("analytics:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Get aggregated analytics summary metrics."""
    from app.analytics.api import get_analytics_summary
    return get_analytics_summary(db)


app.include_router(_analytics_router)


# ── Feedback Router ────────────────────────────────────────────────────────────

_feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackCreateRequest(BaseModel):
    rating: str               # positive | negative
    comment: Optional[str] = None
    interaction_id: Optional[str] = None


@_feedback_router.post("")
def submit_feedback(
    body: FeedbackCreateRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("feedback:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Submit user feedback for an interaction."""
    from app.feedback.api import record_feedback
    fb = record_feedback(
        db,
        user_id=claims.user_id,
        rating=body.rating,
        comment=body.comment,
        interaction_id=body.interaction_id,
    )
    db.commit()
    return {"id": str(fb.id), "status": "recorded"}


app.include_router(_feedback_router)


# ── System Settings Router ─────────────────────────────────────────────────────

_admin_router = APIRouter(prefix="/admin", tags=["admin"])


class SystemSettingRequest(BaseModel):
    key: str
    value: str


@_admin_router.get("/settings")
def get_settings_endpoint(
    claims: Annotated[TokenClaims, Depends(require_perm("system:manage"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """List all system settings (admin only)."""
    from app.core.system_settings import get_all_settings
    return {"settings": get_all_settings(db)}


@_admin_router.post("/settings")
def set_setting_endpoint(
    body: SystemSettingRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("system:manage"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Update a system setting (admin only)."""
    from app.core.system_settings import set_setting
    setting = set_setting(db, key=body.key, value=body.value, actor_id=claims.user_id)
    db.commit()
    return {"key": setting.key, "value": setting.value, "status": "updated"}


# ── Knowledge Admin Router ──

class ArticleCreateRequest(BaseModel):
    title: str
    body: str
    type: str = "policy"
    owner: Optional[str] = None
    roles: Optional[list] = None
    source_ref: Optional[str] = None


class PublishRequest(BaseModel):
    note: Optional[str] = None


class RollbackRequest(BaseModel):
    target_version_id: str


@_admin_router.get("/knowledge/articles")
def list_knowledge_articles(
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:read"))],
    query: Optional[str] = None,
    status: Optional[str] = None,
    db: Annotated[object, Depends(get_db)] = None,
):
    """List knowledge articles/nodes with filtering."""
    from app.knowledge.admin import list_articles
    articles = list_articles(db, query=query, status=status)
    return {"articles": articles}


@_admin_router.post("/knowledge/articles")
def create_knowledge_article(
    body: ArticleCreateRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Create a new article node in the active graph version."""
    from app.knowledge.admin import create_article
    node = create_article(
        db,
        title=body.title,
        body=body.body,
        type=body.type,
        owner=body.owner or "Department Operations Head",
        roles=body.roles or ["ALL"],
        source_ref=body.source_ref,
    )
    db.commit()
    return {"id": str(node.id), "title": node.title, "status": node.status}


@_admin_router.post("/knowledge/publish")
def publish_graph(
    body: PublishRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Publish a new graph version as active."""
    from app.knowledge.admin import publish_new_graph_version
    ver = publish_new_graph_version(db, note=body.note or "")
    db.commit()
    return {"version_id": str(ver.id), "status": ver.status}


@_admin_router.post("/knowledge/rollback")
def rollback_graph(
    body: RollbackRequest,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Roll back to a specified graph version."""
    from app.knowledge.admin import rollback_graph_version
    try:
        ver = rollback_graph_version(db, body.target_version_id)
        db.commit()
        return {"version_id": str(ver.id), "status": ver.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


class DraftFromGapBody(BaseModel):
    title: str
    body: str
    owner: Optional[str] = None
    roles: Optional[list[str]] = None
    review_date: Optional[str] = None


class RetireArticleBody(BaseModel):
    superseded_by_id: Optional[str] = None


@_admin_router.get("/knowledge/gaps")
def list_knowledge_gaps(
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """List knowledge gaps (tickets with is_gap=True)."""
    from app.core.models import Ticket
    gaps = db.execute(
        select(Ticket).where(Ticket.is_gap == True).order_by(Ticket.created_at.desc())
    ).scalars().all()
    return {
        "gaps": [
            {
                "id": str(t.id),
                "team": t.team,
                "urgency": t.urgency,
                "reason": t.reason,
                "status": t.status,
                "summary": t.summary,
                "created_at": str(t.created_at),
                "opened_by": str(t.opened_by),
            }
            for t in gaps
        ]
    }


@_admin_router.post("/knowledge/gaps/{ticket_id}/draft")
def draft_from_gap_endpoint(
    ticket_id: str,
    body: DraftFromGapBody,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Create a draft article node from a knowledge gap ticket."""
    from app.knowledge.second_brain import create_draft_from_gap
    from datetime import date
    try:
        t_uuid = uuid.UUID(ticket_id)
        rev_date = date.fromisoformat(body.review_date) if body.review_date else None
        node = create_draft_from_gap(
            db,
            t_uuid,
            title=body.title,
            body=body.body,
            owner=body.owner,
            roles=body.roles,
            review_date=rev_date,
        )
        db.commit()
        return {"id": str(node.id), "title": node.title, "status": node.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


@_admin_router.post("/knowledge/articles/{article_id}/approve")
def approve_article_endpoint(
    article_id: str,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Approve draft article and publish a new graph version with embeddings."""
    from app.knowledge.second_brain import approve_and_publish_article
    try:
        a_uuid = uuid.UUID(article_id)
        ver = approve_and_publish_article(db, a_uuid)
        db.commit()
        return {"version_id": str(ver.id), "status": ver.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


@_admin_router.post("/knowledge/articles/{article_id}/retire")
def retire_article_endpoint(
    article_id: str,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    body: Optional[RetireArticleBody] = None,
    db: Annotated[object, Depends(get_db)] = None,
):
    """Retire/supersede article, deleting embeddings in the same transaction."""
    from app.knowledge.second_brain import retire_article
    try:
        a_uuid = uuid.UUID(article_id)
        sup_uuid = uuid.UUID(body.superseded_by_id) if body and body.superseded_by_id else None
        retire_article(db, a_uuid, superseded_by_id=sup_uuid)
        db.commit()
        return {"id": article_id, "status": "archived"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@_admin_router.get("/knowledge/link-suggestions")
def list_link_suggestions_endpoint(
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """List proposed edge link suggestions."""
    from app.core.models import Edge, Node
    from app.knowledge.api import get_active_version_id
    ver_id = get_active_version_id(db)
    if not ver_id:
        return {"suggestions": []}
    edges = db.execute(
        select(Edge).where(Edge.version_id == ver_id, Edge.origin == "suggested")
    ).scalars().all()

    res = []
    for e in edges:
        from_node = db.execute(select(Node.title).where(Node.id == e.from_id, Node.version_id == ver_id)).scalar_one_or_none()
        to_node = db.execute(select(Node.title).where(Node.id == e.to_id, Node.version_id == ver_id)).scalar_one_or_none()
        res.append({
            "id": e.id,
            "from_id": str(e.from_id),
            "to_id": str(e.to_id),
            "from_title": from_node or str(e.from_id),
            "to_title": to_node or str(e.to_id),
            "type": e.type,
            "origin": e.origin,
            "note": e.note,
        })
    return {"suggestions": res}


@_admin_router.post("/knowledge/link-suggestions/generate")
def generate_link_suggestions_endpoint(
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Run link suggestion worker job."""
    from app.knowledge.second_brain import generate_link_suggestions
    edges = generate_link_suggestions(db)
    db.commit()
    return {"generated_count": len(edges)}


@_admin_router.post("/knowledge/link-suggestions/{edge_id}/approve")
def approve_link_suggestion_endpoint(
    edge_id: int,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Approve a link suggestion edge."""
    from app.core.models import Edge
    from app.knowledge.api import _GRAPH_CACHE
    edge = db.execute(select(Edge).where(Edge.id == edge_id)).scalar_one_or_none()
    if not edge:
        raise HTTPException(404, "Suggestion not found")
    edge.origin = "approved"
    db.commit()
    _GRAPH_CACHE.clear()
    return {"id": edge_id, "origin": "approved"}


@_admin_router.post("/knowledge/link-suggestions/{edge_id}/reject")
def reject_link_suggestion_endpoint(
    edge_id: int,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:write"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Reject and delete a link suggestion edge."""
    from app.core.models import Edge
    edge = db.execute(select(Edge).where(Edge.id == edge_id)).scalar_one_or_none()
    if not edge:
        raise HTTPException(404, "Suggestion not found")
    db.delete(edge)
    db.commit()
    return {"id": edge_id, "status": "deleted"}


@_admin_router.get("/eval/results")
async def get_admin_eval_results_endpoint(
    db: Annotated[object, Depends(get_db)],
):
    """Get latest evaluation results and ablation summary."""
    from app.eval.api import get_eval_results
    return await get_eval_results(db)


@_admin_router.post("/eval/run")
async def run_evaluation_suite_endpoint(
    claims: Annotated[TokenClaims, Depends(require_perm("system:manage"))],
    split: str = "heldout",
    tune: bool = False,
    db: Annotated[object, Depends(get_db)] = None,
):
    """Run evaluation benchmark suite (admin only)."""
    from app.eval.api import trigger_eval_run
    return await trigger_eval_run(split=split, tune=tune, db=db)


app.include_router(_admin_router)

from app.eval.api import router as eval_router
app.include_router(eval_router)



# ── Graph Impact Router ───────────────────────────────────────────────────────

_graph_router = APIRouter(prefix="/graph", tags=["graph"])


@_graph_router.get("/impact/{node_id}")
def get_graph_impact_endpoint(
    node_id: str,
    claims: Annotated[TokenClaims, Depends(require_perm("knowledge:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Get change impact (workflows and articles affected through backlinks)."""
    from app.knowledge.second_brain import get_change_impact
    try:
        n_uuid = uuid.UUID(node_id)
        return get_change_impact(db, n_uuid)
    except ValueError as e:
        raise HTTPException(400, str(e))


app.include_router(_graph_router)


# ── Users Router ──────────────────────────────────────────────────────────────

_users_router = APIRouter(prefix="/users", tags=["users"])


@_users_router.get("")
def list_users(
    claims: Annotated[TokenClaims, Depends(require_perm("users:manage"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """List all users (admin only)."""
    from app.core.models import User, UserDeptRole, DeptRole
    users = db.execute(select(User)).scalars().all()
    out = []
    for u in users:
        role_names = db.execute(
            select(DeptRole.name)
            .join(UserDeptRole, UserDeptRole.dept_role_id == DeptRole.id)
            .where(UserDeptRole.user_id == u.id)
        ).scalars().all()
        out.append({
            "id": str(u.id),
            "email": u.email,
            "name": u.name,
            "app_role": u.app_role,
            "active": u.active,
            "dept_roles": role_names,
            "created_at": str(u.created_at),
        })
    return {"users": out}


app.include_router(_users_router)


# ── Audit Router ──────────────────────────────────────────────────────────────

_audit_router = APIRouter(prefix="/audit", tags=["audit"])


@_audit_router.get("/log")
def audit_log(
    claims: Annotated[TokenClaims, Depends(require_perm("audit:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Get latest audit log entries."""
    from app.core.models import AuditLog
    rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(100)).scalars().all()
    return {"rows": [{"id": r.id, "payload": r.payload, "hash": r.hash, "created_at": str(r.created_at)} for r in rows]}


@_audit_router.get("/verify")
def audit_verify(
    claims: Annotated[TokenClaims, Depends(require_perm("audit:verify"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Recompute the HMAC chain and return verification status."""
    from app.audit.api import verify_chain
    from app.core.models import AuditLog
    ok, violations = verify_chain(db)
    total = db.execute(select(func.count(AuditLog.id))).scalar() or 0
    first_bad_id = violations[0]["id"] if violations else None
    return {
        "ok": ok,
        "rows": total,
        "first_bad_id": first_bad_id,
        "violations": violations,
    }


app.include_router(_audit_router)


# ── Console/tickets endpoints ──────────────────────────────────────────────────

_console_router = APIRouter(prefix="/console", tags=["console"])


class TicketPatchBody(BaseModel):
    action: str          # claim | reassign | resolve
    new_team: Optional[str] = None
    resolution_note: Optional[str] = None


@_console_router.get("/tickets")
def console_list_tickets(
    claims: Annotated[TokenClaims, Depends(require_perm("tickets:read"))],
    team: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Annotated[object, Depends(get_db)] = None,
):
    """List tickets sorted by urgency, filterable by team/status."""
    from app.ticketing.api import list_tickets
    tickets = list_tickets(db, team=team, status=status, limit=limit)
    return {"tickets": tickets}


@_console_router.get("/tickets/{ticket_id}")
def console_get_ticket(
    ticket_id: str,
    claims: Annotated[TokenClaims, Depends(require_perm("tickets:read"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """Get a single ticket with its events."""
    from app.ticketing.api import get_ticket_events, list_tickets
    from app.core.models import Ticket
    t = db.execute(select(Ticket).where(
        Ticket.id == uuid.UUID(ticket_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Ticket not found")
    events = get_ticket_events(db, ticket_id)
    return {
        "ticket": {
            "id": str(t.id),
            "team": t.team,
            "urgency": t.urgency,
            "status": t.status,
            "reason": t.reason,
            "is_gap": t.is_gap,
            "opened_by": str(t.opened_by),
            "assigned_to": str(t.assigned_to) if t.assigned_to else None,
            "summary": t.summary,
            "evidence_ids": t.evidence_ids,
            "created_at": str(t.created_at),
            "resolved_at": str(t.resolved_at) if t.resolved_at else None,
        },
        "events": events,
    }


@_console_router.patch("/tickets/{ticket_id}")
def console_patch_ticket(
    ticket_id: str,
    body: TicketPatchBody,
    claims: Annotated[TokenClaims, Depends(require_perm("tickets:update"))],
    db: Annotated[object, Depends(get_db)] = None,
):
    """
    Claim, reassign, or resolve a ticket.
    Enforces separation of duties: opener cannot claim or resolve their own ticket.
    """
    from app.ticketing.api import claim_ticket, reassign_ticket, resolve_ticket
    try:
        if body.action == "claim":
            ticket = claim_ticket(db, ticket_id, claims.user_id)
        elif body.action == "reassign":
            if not body.new_team:
                raise HTTPException(400, "new_team required for reassign")
            ticket = reassign_ticket(db, ticket_id, claims.user_id, body.new_team)
        elif body.action == "resolve":
            ticket = resolve_ticket(
                db, ticket_id, claims.user_id,
                resolution_note=body.resolution_note or ""
            )
        else:
            raise HTTPException(400, f"Unknown action: {body.action}")
        db.commit()
        return {
            "id": str(ticket.id),
            "status": ticket.status,
            "team": ticket.team,
            "assigned_to": str(ticket.assigned_to) if ticket.assigned_to else None,
        }
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


app.include_router(_console_router)


# ── Legacy tickets router (kept for backward-compat) ───────────────────────────

_tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])


@_tickets_router.get("")
def list_tickets(claims: Annotated[TokenClaims, Depends(require_perm("tickets:read"))],
                 db: Annotated[object, Depends(get_db)] = None):
    from app.ticketing.api import list_tickets as _lt
    return {"tickets": _lt(db)}


app.include_router(_tickets_router)


# ── Workflow session sweep endpoint ───────────────────────────────────────────

_workflow_router = APIRouter(prefix="/workflow", tags=["workflow"])


@_workflow_router.post("/sweep")
def workflow_sweep(claims: Annotated[TokenClaims, Depends(require_perm("system:manage"))]):
    """Sweep expired workflow sessions (admin only)."""
    from app.workflow.session_store import sweep_expired_sessions
    db = SessionLocal()
    try:
        count = sweep_expired_sessions(db)
        return {"swept": count}
    finally:
        db.close()


app.include_router(_workflow_router)
