"""FastAPI dependencies — authentication, permission enforcement.

Design rules (NON-NEGOTIABLE):
- Deterministic code enforces access; LLM prose never drives authz decisions.
- Permission map is a static dict in code — NOT configurable at runtime.
- shift_exp in JWT is compared with wall-clock time; expired shifts -> 401.
- Separation-of-duties: opener cannot approve or resolve their own ticket
  (enforced in ticketing routes, not here, but SoD helper is provided).
"""

from __future__ import annotations

import time
from typing import Annotated

import jwt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import SessionLocal
from app.core.models import User, UserDeptRole, DeptRole
from app.core.security import decode_token
from sqlalchemy import select

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

# ── Permission Map (static, code-level, never runtime-editable) ───────────────
#   Key: permission string   Value: set of app_roles that hold it

_PERM_MAP: dict[str, frozenset[str]] = {
    "chat:use":         frozenset({"employee", "agent", "admin"}),
    "feedback:write":   frozenset({"employee", "agent", "admin"}),
    "tickets:read":     frozenset({"agent", "admin"}),
    "tickets:update":   frozenset({"agent", "admin"}),
    "analytics:read":   frozenset({"admin"}),
    "audit:read":       frozenset({"admin"}),
    "audit:verify":     frozenset({"admin"}),
    "knowledge:read":   frozenset({"admin"}),
    "knowledge:write":  frozenset({"admin"}),
    "users:manage":     frozenset({"admin"}),
    "system:manage":    frozenset({"admin"}),
}


class TokenClaims:
    """Parsed, validated JWT claims attached to a request."""

    def __init__(self, payload: dict) -> None:
        self.user_id: str = payload["sub"]
        self.app_role: str = payload["app_role"]
        self.active_dept_role: str = payload.get("active_dept_role", "")
        self.shift_exp: int | None = payload.get("shift_exp")

    def has_perm(self, perm: str) -> bool:
        allowed = _PERM_MAP.get(perm, frozenset())
        return self.app_role in allowed


def _get_claims(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> TokenClaims:
    """Decode Bearer token and enforce shift_exp."""
    try:
        payload = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected access token")

    claims = TokenClaims(payload)

    # Enforce shift expiry if present
    if claims.shift_exp is not None and int(time.time()) > claims.shift_exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Shift has ended — please re-authenticate",
        )

    return claims


# Public dependency
get_claims = Depends(_get_claims)


def require_perm(perm: str):
    """FastAPI dependency factory. Usage: Depends(require_perm('analytics:read'))"""

    def _check(claims: Annotated[TokenClaims, Depends(_get_claims)]) -> TokenClaims:
        if not claims.has_perm(perm):
            logger.warning(
                "permission_denied",
                user_id=claims.user_id,
                app_role=claims.app_role,
                required_perm=perm,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{perm}' required",
            )
        return claims

    return _check


# ── Separation-of-duties helper ───────────────────────────────────────────────

def assert_not_opener(ticket_opened_by: str, claims: TokenClaims, action: str = "act on") -> None:
    """Raise 403 if the current user opened the ticket (SoD enforcement)."""
    if str(ticket_opened_by) == str(claims.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Separation of duties: you cannot {action} a ticket you opened",
        )


# ── Convenience typed deps ────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
