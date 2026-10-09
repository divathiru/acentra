"""
Session store for workflow slot state.

Key:  sha256(user_id + encounter_hash + dept) — user-scoped, never shared.
TTL:  30 minutes from last update.
Sensitive slots (MRN, SSN, DOB) stored ONLY in Fernet-encrypted vault_json_encrypted.
All other slots stored in slots_json (plain JSONB).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Tuple

import structlog
from cryptography.fernet import Fernet
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.models import WorkflowSession

logger = structlog.get_logger(__name__)

SESSION_TTL_MINUTES = 30
_SENSITIVE_FIELD_PATTERNS = frozenset({"mrn", "patient_mrn", "ssn", "dob", "date_of_birth"})


def _is_sensitive(name: str) -> bool:
    return any(p in name.lower() for p in _SENSITIVE_FIELD_PATTERNS)


def _get_fernet() -> Fernet:
    key = os.environ.get("VAULT_KEY")
    if not key:
        # Generate a deterministic fallback for dev (NOT production safe)
        key = Fernet.generate_key().decode()
        logger.warning("session.vault_key_missing", note="using ephemeral key — data will be lost on restart")
        return Fernet(Fernet.generate_key())
    try:
        return Fernet(key.encode())
    except Exception:
        # Try base64-encoded
        import base64
        raw = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(raw)


def _make_session_key(user_id: str, workflow_id: str, encounter_id: str, dept: str) -> str:
    """
    Compute a user-scoped, encounter-scoped session key.
    Never shared across users.
    """
    raw = f"{user_id}|{workflow_id}|{encounter_id}|{dept}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── Postgres SessionStore ────────────────────────────────────────────────────

class SessionStore:
    """
    Postgres-backed workflow session store.
    Encrypts sensitive slots with Fernet.
    """

    def __init__(self, db: Session):
        self.db = db
        self._fernet = _get_fernet()

    def _encrypt_vault(self, vault: Dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(vault).encode())

    def _decrypt_vault(self, data: bytes) -> Dict[str, Any]:
        try:
            return json.loads(self._fernet.decrypt(data).decode())
        except Exception:
            logger.error("session.vault_decrypt_failed")
            return {}

    def get_or_create(
        self,
        user_id: str,
        workflow_id: str,
        encounter_id: str,
        dept: str,
        article_version: Optional[int] = None,
    ) -> Tuple[WorkflowSession, bool]:
        """
        Return (session, created). If session exists and is not expired, return it.
        If expired, purge and create fresh.
        """
        key = _make_session_key(user_id, workflow_id, encounter_id, dept)
        existing = self.db.execute(
            select(WorkflowSession).where(
                WorkflowSession.key == key,
                WorkflowSession.user_id == user_id,
            )
        ).scalar_one_or_none()

        if existing:
            if existing.expires_at and existing.expires_at < _now_utc():
                # Expired — purge
                self.db.delete(existing)
                self.db.flush()
                existing = None
            else:
                return existing, False

        # Create new
        sess = WorkflowSession(
            user_id=user_id,
            key=key,
            workflow_id=workflow_id,
            article_version=article_version,
            slots_json={},
            vault_json_encrypted=None,
            expires_at=_now_utc() + timedelta(minutes=SESSION_TTL_MINUTES),
        )
        self.db.add(sess)
        self.db.flush()
        return sess, True

    def get(self, user_id: str, workflow_id: str, encounter_id: str, dept: str) -> Optional[WorkflowSession]:
        key = _make_session_key(user_id, workflow_id, encounter_id, dept)
        sess = self.db.execute(
            select(WorkflowSession).where(
                WorkflowSession.key == key,
                WorkflowSession.user_id == user_id,
            )
        ).scalar_one_or_none()
        if sess and sess.expires_at and sess.expires_at < _now_utc():
            self.db.delete(sess)
            self.db.flush()
            return None
        return sess

    def get_slots(self, sess: WorkflowSession) -> Dict[str, Any]:
        """Return all non-sensitive slots."""
        return dict(sess.slots_json or {})

    def get_vault_keys(self, sess: WorkflowSession) -> Set[str]:
        """Return set of field names in the encrypted vault."""
        if not sess.vault_json_encrypted:
            return set()
        vault = self._decrypt_vault(sess.vault_json_encrypted)
        return set(vault.keys())

    def set_slots(
        self,
        sess: WorkflowSession,
        new_slots: Dict[str, Any],
        sensitive_field_names: Optional[Set[str]] = None,
    ) -> None:
        """
        Merge new_slots into session. Sensitive values go to encrypted vault.
        Sensitive values are NEVER written to slots_json.
        Refresh TTL.
        """
        sensitive_field_names = sensitive_field_names or set()
        plain_slots = dict(sess.slots_json or {})
        vault: Dict[str, Any] = {}
        if sess.vault_json_encrypted:
            vault = self._decrypt_vault(sess.vault_json_encrypted)

        for k, v in new_slots.items():
            if k in sensitive_field_names or _is_sensitive(k):
                vault[k] = v
                # Ensure the key is NOT in plain slots
                plain_slots.pop(k, None)
            else:
                plain_slots[k] = v

        sess.slots_json = plain_slots
        sess.vault_json_encrypted = self._encrypt_vault(vault) if vault else None
        sess.expires_at = _now_utc() + timedelta(minutes=SESSION_TTL_MINUTES)
        self.db.flush()

    def purge(self, sess: WorkflowSession) -> None:
        """Delete the session (workflow complete or abandoned)."""
        self.db.delete(sess)
        self.db.flush()

    def check_article_version_drift(
        self, sess: WorkflowSession, current_version: Optional[int]
    ) -> bool:
        """Return True if the governing article version changed since session pinned."""
        if sess.article_version and current_version and sess.article_version != current_version:
            return True
        return False


def sweep_expired_sessions(db: Session) -> int:
    """Delete all expired workflow sessions. Call from a background task/cron."""
    result = db.execute(
        delete(WorkflowSession).where(WorkflowSession.expires_at < _now_utc())
    )
    db.commit()
    count = result.rowcount
    if count:
        logger.info("session.sweep", expired=count)
    return count
