"""
Demo reset script — restores interactions, tickets and audit rows to the
scripted demo state without wiping the knowledge graph or user table.

Target: completes in < 20 seconds on local Docker.
Run via:  docker compose exec api python -m app.demo_reset
          or: make demo-data   (which calls this file)
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.models import (
    AuditLog,
    Interaction,
    Ticket,
    User,
)
from app.audit.api import write_audit_event

# ── Scripted demo interactions ────────────────────────────────────────────────
# Each entry maps to a demo step in docs/DEMO.md.
# These are inserted verbatim so the admin analytics dashboard shows
# realistic, predictable data for the demo.

_DEMO_INTERACTIONS = [
    # step 1: grounded ANSWER
    dict(
        outcome="ANSWER", intent="policy_lookup", band="HIGH",
        mode="template", dept_role="Billing", confidence=0.91,
        latency_ms=180, citation_ok=True, feedback="positive",
    ),
    # step 2: MRI GUIDE workflow
    dict(
        outcome="GUIDE", intent="workflow_guidance", band="HIGH",
        mode="template", dept_role="Radiology", confidence=0.88,
        latency_ms=210, citation_ok=True, feedback="positive",
        workflow_id="W-001",
    ),
    # step 3: honest uncertainty / LOW band → ROUTE gap
    dict(
        outcome="ROUTE", intent="policy_lookup", band="LOW",
        mode="template", dept_role="Insurance/TPA", confidence=0.31,
        latency_ms=165, citation_ok=False, is_gap=True,
    ),
    # step 4: gap closes → ANSWER (simulated approved article)
    dict(
        outcome="ANSWER", intent="policy_lookup", band="HIGH",
        mode="template", dept_role="Insurance/TPA", confidence=0.87,
        latency_ms=175, citation_ok=True, feedback="positive",
    ),
    # step 5: specimen rejection ROUTE
    dict(
        outcome="ROUTE", intent="lab_rejection", band="MEDIUM",
        mode="template", dept_role="Lab", confidence=0.62,
        latency_ms=195, citation_ok=True,
    ),
    # step 6: clinical REFUSE
    dict(
        outcome="REFUSE", intent="clinical_question", band="HIGH",
        mode="template", dept_role="Discharge", confidence=0.99,
        latency_ms=55, citation_ok=False,
    ),
    # step 7a: billing role question
    dict(
        outcome="ANSWER", intent="billing_inquiry", band="HIGH",
        mode="template", dept_role="Billing", confidence=0.85,
        latency_ms=185, citation_ok=True,
    ),
    # step 7b: same question different role (Billing Supervisor)
    dict(
        outcome="ANSWER", intent="billing_inquiry", band="HIGH",
        mode="template", dept_role="Billing Supervisor", confidence=0.85,
        latency_ms=190, citation_ok=True,
    ),
    # step 8: change impact (no interaction — graph operation only)
    # step 9: LLM killed → template fallback
    dict(
        outcome="ANSWER", intent="policy_lookup", band="MEDIUM",
        mode="template", dept_role="Front Office", confidence=0.72,
        latency_ms=95, citation_ok=True,
    ),
    # step 10: audit tamper + verify (handled by audit module)
    dict(
        outcome="ANSWER", intent="policy_lookup", band="HIGH",
        mode="template", dept_role="Front Office", confidence=0.89,
        latency_ms=180, citation_ok=True,
    ),
    # Additional background traffic so the dashboard looks alive
    *[
        dict(
            outcome=random.choices(
                ["ANSWER", "GUIDE", "ROUTE", "REFUSE"],
                weights=[0.55, 0.20, 0.18, 0.07],
            )[0],
            intent=random.choice(
                ["policy_lookup", "workflow_guidance", "billing_inquiry",
                 "lab_rejection", "it_request"]
            ),
            band=random.choice(["HIGH", "MEDIUM", "LOW"]),
            mode=random.choices(["template", "llm"], weights=[0.85, 0.15])[0],
            dept_role=random.choice(
                ["Billing", "Radiology", "Lab", "Discharge",
                 "Front Office", "Admission", "IT Support"]
            ),
            confidence=round(random.uniform(0.35, 0.97), 2),
            latency_ms=random.randint(60, 900),
            citation_ok=random.random() < 0.88,
            feedback=random.choices(
                ["positive", "negative", None],
                weights=[0.60, 0.08, 0.32],
            )[0],
            is_gap=random.random() < 0.07,
        )
        for _ in range(130)
    ],
]

_DEMO_TICKETS = [
    # Gap ticket from step 3
    dict(
        team="Department Operations Head",
        urgency="normal",
        reason="Insufficient evidence — knowledge gap captured for review",
        is_gap=True,
        status="open",
    ),
    # Specimen rejection ticket from step 5
    dict(
        team="Lab",
        urgency="high",
        reason="Hemolysis specimen rejection — protocol clarification required",
        is_gap=False,
        status="in_progress",
    ),
    # Billing dispute
    dict(
        team="Billing Supervisor",
        urgency="normal",
        reason="Discharge billing amount exceeds approval threshold",
        is_gap=False,
        status="open",
    ),
    # MRI auth pending
    dict(
        team="Radiology",
        urgency="normal",
        reason="MRI pre-authorization pending — insurer response awaited",
        is_gap=False,
        status="open",
    ),
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def generate_demo_data(session) -> None:
    t0 = time.perf_counter()
    print("🔄  Resetting demo interactions, tickets and audit rows …")

    # ── Truncate transient tables only (preserves graph, users, knowledge) ──
    session.execute(text(
        "TRUNCATE interactions, tickets, audit_log, "
        "feedback, conversations, messages RESTART IDENTITY CASCADE"
    ))
    session.commit()

    # ── Re-seed from user table ──
    user = session.query(User).first()
    user_id = user.id if user else None
    now = _now_utc()

    # Interactions
    for i, spec in enumerate(_DEMO_INTERACTIONS):
        days_ago = max(0, (len(_DEMO_INTERACTIONS) - i) // 10)
        ts = now - timedelta(days=days_ago, hours=(i % 24), minutes=(i * 7 % 60))
        is_gap = spec.get("is_gap", False)
        iact = Interaction(
            id=uuid.uuid4(),
            ts=ts,
            user_id=user_id,
            dept_role=spec["dept_role"],
            outcome=spec["outcome"],
            intent=spec["intent"],
            workflow_id=spec.get("workflow_id"),
            confidence=spec["confidence"],
            band=spec["band"],
            latency_ms=spec["latency_ms"],
            mode=spec["mode"],
            is_gap=is_gap,
            citation_ok=spec["citation_ok"],
            feedback=spec.get("feedback"),
        )
        session.add(iact)

    # Tickets
    for spec in _DEMO_TICKETS:
        days_ago = random.randint(0, 7)
        ts = now - timedelta(days=days_ago)
        session.add(Ticket(
            id=uuid.uuid4(),
            team=spec["team"],
            urgency=spec["urgency"],
            reason=spec["reason"],
            is_gap=spec["is_gap"],
            status=spec["status"],
            opened_by=user_id,
            created_at=ts,
        ))

    session.commit()

    elapsed = (time.perf_counter() - t0) * 1000
    print(f"✅  Demo reset complete in {elapsed:.0f} ms  "
          f"({len(_DEMO_INTERACTIONS)} interactions, {len(_DEMO_TICKETS)} tickets)")

    if elapsed > 20_000:
        print("⚠️   WARNING: demo reset took > 20 seconds — check DB performance")


if __name__ == "__main__":
    with SessionLocal() as session:
        generate_demo_data(session)
