"""Auth router — login, refresh, persona switch, me.

Endpoints:
  POST /auth/login    → access_token + refresh_token
  POST /auth/refresh  → new access_token (from refresh token)
  POST /auth/persona  → switch active_dept_role; re-issues access token; audited
  GET  /auth/me       → current user info (no sensitive fields)
"""

from __future__ import annotations

import time
from typing import Annotated

import jwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.deps import TokenClaims, _get_claims, get_db, require_perm
from app.core.models import AuditLog, DeptRole, Shift, User, UserDeptRole
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.audit.api import write_audit_event

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PersonaRequest(BaseModel):
    dept_role: str


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    app_role: str
    active_dept_role: str
    dept_roles: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_active_shift_exp(db: Session, user_id) -> int | None:
    """Return shift_exp (unix ts) if user has an active shift, else None."""
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    row = db.execute(
        select(Shift).where(
            Shift.user_id == user_id,
            Shift.start_time <= now,
            Shift.end_time >= now,
        )
    ).scalar()
    if row is None:
        return None
    return int(row.end_time.timestamp())


def _get_dept_roles(db: Session, user_id) -> list[str]:
    rows = db.execute(
        select(DeptRole.name)
        .join(UserDeptRole, UserDeptRole.dept_role_id == DeptRole.id)
        .where(UserDeptRole.user_id == user_id)
    ).scalars().all()
    return list(rows)


def _issue_tokens(db: Session, user: User, active_dept_role: str) -> LoginResponse:
    shift_exp = _get_active_shift_exp(db, user.id)
    access = create_access_token(
        user_id=str(user.id),
        app_role=user.app_role,
        active_dept_role=active_dept_role,
        shift_exp=shift_exp,
    )
    refresh = create_refresh_token(user_id=str(user.id))
    return LoginResponse(access_token=access, refresh_token=refresh)


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(body.password, user.password_hash):
        logger.warning("auth.login_failed", email=body.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Default dept role = first alphabetically
    dept_roles = _get_dept_roles(db, user.id)
    active_dept_role = dept_roles[0] if dept_roles else ""

    logger.info("auth.login_ok", user_id=str(user.id), app_role=user.app_role)
    return _issue_tokens(db, user, active_dept_role)


# ── POST /auth/refresh ────────────────────────────────────────────────────────

@router.post("/refresh", response_model=LoginResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    user = db.get(User, payload["sub"])
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    dept_roles = _get_dept_roles(db, user.id)
    active_dept_role = dept_roles[0] if dept_roles else ""
    return _issue_tokens(db, user, active_dept_role)


# ── POST /auth/persona ────────────────────────────────────────────────────────

@router.post("/persona", response_model=LoginResponse)
def switch_persona(
    body: PersonaRequest,
    claims: Annotated[TokenClaims, Depends(_get_claims)],
    db: Session = Depends(get_db),
):
    """Switch the active dept role; emits an audit event."""
    user = db.get(User, claims.user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    dept_roles = _get_dept_roles(db, user.id)
    if body.dept_role not in dept_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not hold the dept role '{body.dept_role}'",
        )

    write_audit_event(
        db,
        event_type="persona.switch",
        payload={
            "user_id": claims.user_id,
            "from_role": claims.active_dept_role,
            "to_role": body.dept_role,
        },
    )

    logger.info(
        "auth.persona_switch",
        user_id=claims.user_id,
        from_role=claims.active_dept_role,
        to_role=body.dept_role,
    )
    return _issue_tokens(db, user, body.dept_role)


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=MeResponse)
def me(
    claims: Annotated[TokenClaims, Depends(_get_claims)],
    db: Session = Depends(get_db),
):
    user = db.get(User, claims.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    dept_roles = _get_dept_roles(db, user.id)
    return MeResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        app_role=user.app_role,
        active_dept_role=claims.active_dept_role,
        dept_roles=dept_roles,
    )
