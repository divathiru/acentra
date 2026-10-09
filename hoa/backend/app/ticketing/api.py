"""
Ticketing module — create, list, update tickets with:
- Idempotency key deduplication (60-min window within same encounter)
- Urgency from intent.urgency + sentiment signal
- Separation of duties on claim/resolve
- Full ticket_events audit trail
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.core.models import Ticket, TicketEvent, User, AuditLog
from app.audit.api import write_audit_event

logger = structlog.get_logger(__name__)

DEDUPE_WINDOW_MINUTES = 60


# ─── Urgency classification ──────────────────────────────────────────────────

def _classify_urgency(intent_urgency: Optional[str], query_lower: str) -> str:
    """Combine intent urgency with simple sentiment signals."""
    urgent_keywords = {
        "urgent", "emergency", "asap", "immediately", "critical",
        "stat", "now", "right now", "immediately",
    }
    low_keywords = {"whenever", "no rush", "low priority", "when available", "not urgent"}

    if any(k in query_lower for k in urgent_keywords):
        return "urgent"
    if any(k in query_lower for k in low_keywords):
        return "low"
    if intent_urgency in ("urgent", "high"):
        return "urgent"
    if intent_urgency == "low":
        return "low"
    return "normal"


# ─── Idempotency key deduplication ──────────────────────────────────────────

def _encounter_hash(user_id: str, encounter_id: str, reason: str) -> str:
    raw = f"{user_id}|{encounter_id}|{reason}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _find_duplicate_ticket(
    db: Session,
    encounter_hash: str,
    user_id: str,
    idempotency_key: Optional[str],
) -> Optional[Ticket]:
    """
    Check for a duplicate ticket within the 60-minute deduplication window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUPE_WINDOW_MINUTES)

    # First check idempotency_key via TicketEvent data
    if idempotency_key:
        events = db.execute(
            select(TicketEvent).where(
                TicketEvent.event_type == "opened",
                TicketEvent.created_at > cutoff,
            )
        ).scalars().all()
        for event in events:
            data = event.data or {}
            if data.get("idempotency_key") == idempotency_key:
                ticket = db.execute(
                    select(Ticket).where(Ticket.id == event.ticket_id)
                ).scalar_one_or_none()
                if ticket:
                    logger.info("ticket.dedupe_idempotency", ticket_id=str(ticket.id))
                    return ticket

    # Then check by encounter hash
    recent_events = db.execute(
        select(TicketEvent).where(
            TicketEvent.event_type == "opened",
            TicketEvent.created_at > cutoff,
        )
    ).scalars().all()
    for event in recent_events:
        data = event.data or {}
        if data.get("encounter_hash") == encounter_hash:
            ticket = db.execute(
                select(Ticket).where(Ticket.id == event.ticket_id)
            ).scalar_one_or_none()
            if ticket and str(ticket.opened_by) == str(user_id):
                logger.info("ticket.dedupe_encounter", ticket_id=str(ticket.id))
                return ticket

    return None


# ─── Create ticket ───────────────────────────────────────────────────────────

def create_ticket(
    db: Session,
    *,
    team: str,
    reason: str,
    summary: str,
    opened_by: str,
    evidence_ids: Optional[List[str]] = None,
    urgency: Optional[str] = None,
    intent_urgency: Optional[str] = None,
    query: str = "",
    idempotency_key: Optional[str] = None,
    encounter_id: str = "default",
    suggested_owner: Optional[str] = None,
    dept_role: Optional[str] = None,
    assistant_text: Optional[str] = None,
    is_gap: bool = False,
) -> Ticket:
    """
    Create a ticket with idempotency deduplication.
    Returns the existing ticket if a duplicate is found.
    """
    final_urgency = _classify_urgency(intent_urgency or urgency, query.lower())
    enc_hash = _encounter_hash(str(opened_by), encounter_id, reason)

    # Deduplication check
    existing = _find_duplicate_ticket(db, enc_hash, str(opened_by), idempotency_key)
    if existing:
        logger.info("ticket.reusing_existing", ticket_id=str(existing.id))
        return existing

    # Build ticket
    ticket_id = uuid.uuid4()
    try:
        uid = uuid.UUID(str(opened_by))
    except (ValueError, AttributeError):
        uid = uuid.uuid5(uuid.NAMESPACE_DNS, str(opened_by))

    ticket = Ticket(
        id=ticket_id,
        team=team,
        urgency=final_urgency,
        reason=reason,
        is_gap=is_gap,
        status="open",
        opened_by=uid,
        summary=summary[:500],  # truncate — no raw PII
        evidence_ids=evidence_ids or [],
    )
    db.add(ticket)
    db.flush()

    # Opening event
    event = TicketEvent(
        ticket_id=ticket_id,
        actor_id=uid,
        event_type="opened",
        data={
            "reason": reason,
            "urgency": final_urgency,
            "team": team,
            "idempotency_key": idempotency_key,
            "encounter_hash": enc_hash,
            "suggested_owner": suggested_owner,
            "dept_role": dept_role,
            # assistant_text stored redacted (no raw PII)
            "assistant_text_len": len(assistant_text) if assistant_text else 0,
        },
    )
    db.add(event)
    db.flush()

    # Audit trail
    write_audit_event(db, "ticket_opened", {
        "ticket_id": str(ticket_id),
        "team": team,
        "urgency": final_urgency,
        "reason": reason,
        "opened_by": str(uid),
        "encounter_hash": enc_hash,
    })

    logger.info(
        "ticket.created",
        ticket_id=str(ticket_id),
        team=team,
        urgency=final_urgency,
        reason=reason,
    )
    return ticket


# ─── Claim / Reassign / Resolve ──────────────────────────────────────────────

def claim_ticket(db: Session, ticket_id: str, actor_id: str) -> Ticket:
    """Agent claims a ticket. Cannot claim their own ticket (self-assignment check)."""
    ticket = _get_ticket_or_404(db, ticket_id)

    if ticket.status != "open":
        raise ValueError(f"Cannot claim ticket in status '{ticket.status}'")

    try:
        actor_uuid = uuid.UUID(str(actor_id))
    except ValueError:
        actor_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(actor_id))

    # Separation of duties: cannot claim ticket you opened
    if str(ticket.opened_by) == str(actor_uuid):
        raise PermissionError("Cannot claim a ticket you opened (separation of duties)")

    ticket.assigned_to = actor_uuid
    ticket.status = "in_progress"
    db.flush()

    _add_event(db, ticket.id, actor_uuid, "claimed", {})
    write_audit_event(db, "ticket_claimed", {
        "ticket_id": ticket_id,
        "actor_id": str(actor_uuid),
    })
    logger.info("ticket.claimed", ticket_id=ticket_id, actor=str(actor_uuid))
    return ticket


def reassign_ticket(db: Session, ticket_id: str, actor_id: str, new_team: str) -> Ticket:
    """Reassign to a different team."""
    ticket = _get_ticket_or_404(db, ticket_id)

    try:
        actor_uuid = uuid.UUID(str(actor_id))
    except ValueError:
        actor_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(actor_id))

    old_team = ticket.team
    ticket.team = new_team
    db.flush()

    _add_event(db, ticket.id, actor_uuid, "reassigned", {"from": old_team, "to": new_team})
    write_audit_event(db, "ticket_reassigned", {
        "ticket_id": ticket_id,
        "actor_id": str(actor_uuid),
        "from_team": old_team,
        "to_team": new_team,
    })
    logger.info("ticket.reassigned", ticket_id=ticket_id, from_team=old_team, to_team=new_team)
    return ticket


def resolve_ticket(
    db: Session,
    ticket_id: str,
    actor_id: str,
    resolution_note: str = "",
) -> Ticket:
    """
    Resolve a ticket. Separation of duties: the resolver cannot be the opener.
    """
    ticket = _get_ticket_or_404(db, ticket_id)

    try:
        actor_uuid = uuid.UUID(str(actor_id))
    except ValueError:
        actor_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(actor_id))

    # Separation of duties: cannot resolve ticket you opened
    if str(ticket.opened_by) == str(actor_uuid):
        raise PermissionError("Cannot resolve a ticket you opened (separation of duties)")

    if ticket.status == "resolved":
        raise ValueError("Ticket is already resolved")

    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    db.flush()

    _add_event(db, ticket.id, actor_uuid, "resolved", {
        "resolution_note": resolution_note[:500],
    })
    write_audit_event(db, "ticket_resolved", {
        "ticket_id": ticket_id,
        "actor_id": str(actor_uuid),
        "resolution_note": resolution_note[:100],
    })
    logger.info("ticket.resolved", ticket_id=ticket_id, actor=str(actor_uuid))
    return ticket


# ─── List tickets ──────────────────────────────────────────────────────────

URGENCY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def list_tickets(
    db: Session,
    *,
    team: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return tickets sorted by urgency, filtered by team/status."""
    q = select(Ticket)
    if team:
        q = q.where(Ticket.team == team)
    if status:
        q = q.where(Ticket.status == status)

    tickets = db.execute(q.limit(limit * 3)).scalars().all()

    # Sort by urgency
    tickets_sorted = sorted(
        tickets,
        key=lambda t: (URGENCY_ORDER.get(t.urgency, 99), t.created_at or datetime.min),
    )[:limit]

    return [_ticket_to_dict(t) for t in tickets_sorted]


def get_ticket_events(db: Session, ticket_id: str) -> List[Dict[str, Any]]:
    events = db.execute(
        select(TicketEvent)
        .where(TicketEvent.ticket_id == uuid.UUID(ticket_id))
        .order_by(TicketEvent.created_at)
    ).scalars().all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "actor_id": str(e.actor_id) if e.actor_id else None,
            "data": e.data,
            "created_at": str(e.created_at),
        }
        for e in events
    ]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_ticket_or_404(db: Session, ticket_id: str) -> Ticket:
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise ValueError(f"Invalid ticket ID: {ticket_id}")
    ticket = db.execute(select(Ticket).where(Ticket.id == tid)).scalar_one_or_none()
    if not ticket:
        raise ValueError(f"Ticket not found: {ticket_id}")
    return ticket


def _add_event(
    db: Session,
    ticket_id: uuid.UUID,
    actor_id: uuid.UUID,
    event_type: str,
    data: Dict[str, Any],
) -> None:
    event = TicketEvent(
        ticket_id=ticket_id,
        actor_id=actor_id,
        event_type=event_type,
        data=data,
    )
    db.add(event)
    db.flush()


def _ticket_to_dict(t: Ticket) -> Dict[str, Any]:
    return {
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
        "created_at": str(t.created_at) if t.created_at else None,
        "resolved_at": str(t.resolved_at) if t.resolved_at else None,
    }
