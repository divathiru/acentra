"""Password hashing and JWT utilities.

Rules:
- Argon2id for password hashing (argon2-cffi).
- HS256 JWT; access tokens (15 min) carry: sub, app_role, active_dept_role, shift_exp.
- Refresh tokens (7 days) carry only: sub, type=refresh.
- Deterministic code decides everything; LLM never sees raw tokens.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import get_settings

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _settings():
    return get_settings()


def create_access_token(
    *,
    user_id: str,
    app_role: str,
    active_dept_role: str,
    shift_exp: int | None = None,
) -> str:
    """Mint a short-lived access JWT (15 min)."""
    settings = _settings()
    now = int(time.time())
    exp = now + (ACCESS_TOKEN_MINUTES * 60)
    payload: dict[str, Any] = {
        "sub": user_id,
        "app_role": app_role,
        "active_dept_role": active_dept_role,
        "iat": now,
        "exp": exp,
        "type": "access",
    }
    if shift_exp is not None:
        payload["shift_exp"] = shift_exp
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(*, user_id: str) -> str:
    """Mint a long-lived refresh JWT (7 days)."""
    settings = _settings()
    now = int(time.time())
    exp = now + (REFRESH_TOKEN_DAYS * 86400)
    payload = {"sub": user_id, "iat": now, "exp": exp, "type": "refresh"}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    settings = _settings()
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
