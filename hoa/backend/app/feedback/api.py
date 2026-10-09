"""
Feedback module — user feedback submission and retrieval.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Feedback, Interaction
from app.audit.api import write_audit_event

logger = structlog.get_logger(__name__)


def record_feedback(
    db: Session,
    *,
    user_id: str,
    rating: str,                          # positive | negative | 1-5
    comment: Optional[str] = None,
    interaction_id: Optional[str] = None,
) -> Feedback:
    """Record user feedback and update interaction if present."""
    try:
        u_uuid = uuid.UUID(str(user_id))
    except ValueError:
        u_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))

    i_uuid = None
    if interaction_id:
        try:
            i_uuid = uuid.UUID(str(interaction_id))
        except ValueError:
            pass

    fb = Feedback(
        user_id=u_uuid,
        interaction_id=i_uuid,
        rating=rating,
        comment=comment,
    )
    db.add(fb)
    db.flush()

    if i_uuid:
        interaction = db.execute(
            select(Interaction).where(Interaction.id == i_uuid)
        ).scalar_one_or_none()
        if interaction:
            interaction.feedback = rating
            db.flush()

    write_audit_event(db, "feedback_submitted", {
        "feedback_id": str(fb.id),
        "user_id": str(u_uuid),
        "rating": rating,
        "interaction_id": str(i_uuid) if i_uuid else None,
    })

    logger.info("feedback.recorded", feedback_id=str(fb.id), rating=rating)
    return fb
