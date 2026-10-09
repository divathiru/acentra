"""
System settings helper functions — database-backed key-value store.
"""

from __future__ import annotations

from typing import Dict, Optional
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import SystemSetting
from app.audit.api import write_audit_event

logger = structlog.get_logger(__name__)

_DEFAULT_SETTINGS = {
    "llm_enabled": "true",
    "llm_model": "mistral-small-latest",
    "high_confidence_threshold": "0.75",
    "medium_confidence_threshold": "0.50",
    "circuit_breaker_open": "false",
}


def get_all_settings(db: Session) -> Dict[str, str]:
    """Return all system settings, merged with defaults."""
    settings = dict(_DEFAULT_SETTINGS)
    rows = db.execute(select(SystemSetting)).scalars().all()
    for row in rows:
        settings[row.key] = row.value
    return settings


def get_setting(db: Session, key: str, default: Optional[str] = None) -> str:
    """Get a single setting value."""
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row:
        return row.value
    return _DEFAULT_SETTINGS.get(key, default or "")


def set_setting(db: Session, key: str, value: str, actor_id: str = "system") -> SystemSetting:
    """Set a system setting and log an audit event."""
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if not row:
        row = SystemSetting(key=key, value=str(value))
        db.add(row)
    else:
        row.value = str(value)

    db.flush()

    write_audit_event(db, "system_setting_updated", {
        "key": key,
        "value": str(value),
        "actor_id": actor_id,
    })

    logger.info("system_setting.updated", key=key, value=value, actor=actor_id)
    return row
