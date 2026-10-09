"""Public interface for the audit module."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import AuditLog

logger = structlog.get_logger(__name__)


def _compute_hash(payload: dict, prev_hash: str | None) -> str:
    key = get_settings().AUDIT_HMAC_KEY.encode()
    msg = json.dumps({"payload": payload, "prev_hash": prev_hash}, sort_keys=True).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def write_audit_event(db: Session, event_type: str, payload: dict[str, Any]) -> AuditLog:
    """Append a HMAC-chained audit log entry."""
    full_payload = {"event_type": event_type, **payload}

    # Fetch latest hash for chain
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.hash if last else None

    h = _compute_hash(full_payload, prev_hash)
    entry = AuditLog(payload=full_payload, prev_hash=prev_hash, hash=h)
    db.add(entry)
    db.flush()  # Get ID without committing — caller commits

    logger.info("audit.write", event_type=event_type, id=entry.id)
    return entry


def verify_chain(db: Session) -> tuple[bool, list[dict]]:
    """Walk the entire audit log chain and report any broken links."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    violations: list[dict] = []
    prev_hash = None
    for row in rows:
        expected = _compute_hash(row.payload, prev_hash)
        if expected != row.hash:
            violations.append({"id": row.id, "expected": expected, "got": row.hash})
        prev_hash = row.hash
    return (len(violations) == 0, violations)
