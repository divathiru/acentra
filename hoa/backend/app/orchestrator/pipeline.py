"""
Full orchestrator pipeline: Guard → Understand → Retrieve → Verify → Decide → Generate → Record.
"""
from __future__ import annotations

import time
import uuid
import json
from typing import Optional, AsyncGenerator

import structlog
from sqlalchemy.orm import Session

from app.guard.api import scan_input, scan_output
from app.llm.understand import understand, QueryIntent
from app.llm.api import LLMPort
from app.knowledge.api import retrieve, RetrieveFlags, EvidenceBundle
from app.knowledge.verify import verify_evidence
from app.orchestrator.decide import decide, Decision
from app.orchestrator.generate import generate
from app.core.models import (
    Message, Interaction, Ticket, TicketEvent, Conversation, AuditLog, PolicyThreshold, SystemSetting
)
from app.audit.api import write_audit_event

logger = structlog.get_logger(__name__)


# ─── Response schema ──────────────────────────────────────────────────────────

from pydantic import BaseModel
from typing import List, Dict, Any


class Citation(BaseModel):
    id: str
    title: str
    version: int = 1


class Confidence(BaseModel):
    score: float
    band: str
    coverage: Dict[str, bool]
    reasons: List[str]


class ChatResponse(BaseModel):
    outcome: str
    text: str
    citations: List[Citation] = []
    confidence: Confidence
    next_fields: List[str] = []
    ticket: Optional[str] = None
    subgraph: Dict[str, Any] = {}
    mode: str
    banner: Optional[str] = None
    audit_id: Optional[int] = None


# ─── Pipeline ─────────────────────────────────────────────────────────────────

async def run_pipeline(
    query: str,
    user_id: str,
    dept_role: str,
    session: Session,
    llm: LLMPort,
    conversation_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    workflow_slots: Optional[dict] = None,
    required_fields: Optional[list] = None,
    retrieve_flags: Optional[RetrieveFlags] = None,
    override_config: Optional[dict] = None,
) -> tuple[ChatResponse, list[str]]:  # (response, stage_events)
    """
    Run the full pipeline. Returns (ChatResponse, stage_events).
    stage_events is a list of strings for SSE streaming.
    """
    stage_ms: dict = {}
    stage_events: list[str] = []
    workflow_slots = workflow_slots or {}
    required_fields = required_fields or []

    def _tick(stage: str) -> callable:
        t = time.perf_counter()
        def _stop():
            stage_ms[stage] = round((time.perf_counter() - t) * 1000)
        return _stop

    # ── Stage 1: Guard ─────────────────────────────────────────────────────────
    stage_events.append("Checking safety...")
    done = _tick("guard")
    guard_safe, sanitized_query, vault = scan_input(query)
    guard_clinical = (not guard_safe and "dosage" in query.lower() or "diagnos" in query.lower())
    guard_injection = (not guard_safe and not guard_clinical)
    done()

    # ── Stage 2: Understand ────────────────────────────────────────────────────
    stage_events.append("Understanding your request...")
    done = _tick("understand")
    intent = await understand(sanitized_query, llm)
    done()

    # ── Stage 3: Retrieve ──────────────────────────────────────────────────────
    stage_events.append("Searching approved SOPs...")
    done = _tick("retrieve")
    flags = retrieve_flags or RetrieveFlags(use_fts=True, use_graph=True)
    evidence: EvidenceBundle = await retrieve(session, sanitized_query, dept_role, flags)

    # Scan retrieved text for injections
    all_retrieved_text = " ".join(n.get("body", "") for n in evidence.nodes.values())
    from app.guard.api import scan_retrieval
    if not scan_retrieval(all_retrieved_text):
        logger.warning("Injection detected in retrieved knowledge — clearing evidence")
        from app.knowledge.api import EvidenceBundle as EB
        evidence = EB(nodes={}, edges=[], entry_nodes=[], rrf_scores={},
                      top1_cosine=0.0, conflict_flag=False, conflict_owners=[],
                      superseded_notes={})
    done()

    # ── Stage 4: Verify ────────────────────────────────────────────────────────
    stage_events.append("Verifying sources...")
    done = _tick("verify")
    config = _load_thresholds(session)
    if override_config:
        config.update(override_config)
    verification = verify_evidence(evidence, expected_entities=max(1, len(intent.entities.model_dump(exclude_none=True))), resolved_entities=len(evidence.entry_nodes), config=config)
    done()

    # ── Stage 5: Decide ────────────────────────────────────────────────────────
    done = _tick("decide")
    decision: Decision = decide(
        guard_safe=guard_safe,
        guard_clinical=guard_clinical,
        guard_injection=guard_injection,
        evidence=evidence,
        verification=verification,
        intent=intent,
        thresholds=config,
        workflow_slots=workflow_slots,
        required_fields=required_fields,
    )
    done()

    # ── Stage 6: Generate ──────────────────────────────────────────────────────
    stage_events.append("Composing answer...")
    done = _tick("generate")
    answer_text = ""
    mode = "template"
    workflow_action = None
    next_fields: list[str] = decision.missing_fields or []
    form_name: Optional[str] = None
    system_name: Optional[str] = None

    # ── Workflow FSM integration ────────────────────────────────────────────────
    if intent.kind == "workflow" and intent.workflow_id:
        from app.workflow.api import run_workflow, identify_workflow
        wf_key = identify_workflow(intent.workflow_id, sanitized_query)
        if wf_key:
            stage_events.append(f"Running {wf_key} workflow...")
            try:
                wf_slots = workflow_slots or {}
                workflow_action, public_slots = run_workflow(
                    workflow_id=wf_key,
                    user_id=user_id,
                    dept=dept_role,
                    new_slots=wf_slots,
                    db=session,
                    thresholds=config,
                    encounter_id=conversation_id or "default",
                )
                answer_text = workflow_action.text
                mode = "template"
                next_fields = workflow_action.prompt_fields
                form_name = workflow_action.form
                system_name = workflow_action.system

                # Map workflow action state to decision outcome
                if workflow_action.state == "COLLECT":
                    decision.outcome = "GUIDE"
                    decision.missing_fields = workflow_action.prompt_fields
                elif workflow_action.state == "GUIDE":
                    decision.outcome = "GUIDE"
                elif workflow_action.state == "ROUTE":
                    decision.outcome = "ROUTE"
                    decision.team = workflow_action.route_team or decision.team
                    decision.reason = workflow_action.route_reason or decision.reason
                    decision.ticket = True
                elif workflow_action.state == "DONE":
                    decision.outcome = "ANSWER"
            except Exception as wf_err:
                logger.warning("workflow.run_error", error=str(wf_err))
                # Fall through to normal pipeline handling

    if not workflow_action:
        # Normal pipeline flow
        if decision.outcome == "ANSWER":
            try:
                answer_text, mode = await generate(
                    query=sanitized_query,
                    bundle=evidence,
                    verification=verification,
                    intent=intent,
                    llm=llm,
                    is_medium_band=(verification.get("band") == "medium"),
                )
            except ValueError:
                # Citation guard failed — escalate to ROUTE
                decision.outcome = "ROUTE"
                decision.reason = "citation_guard_failed"
                decision.team = decision.team or "Department Operations Head"
                decision.ticket = True
                answer_text = "I was unable to generate a verified answer. Your request has been routed to the appropriate team."
                mode = "template"
        elif decision.outcome == "GUIDE":
            if decision.missing_fields:
                field_list = " and ".join(f"**{f}**" for f in decision.missing_fields)
                answer_text = f"To continue, I need a few more details. Could you please provide: {field_list}?"
            else:
                answer_text = "Let's continue the workflow. Please confirm the details collected so far are correct."
            mode = "template"
        elif decision.outcome == "ROUTE":
            team = decision.team or "Operations Team"
            answer_text = decision.banner or f"Your request has been routed to {team} for review."
            if decision.draft:
                answer_text += f"\n\nDraft submitted: {decision.draft}"
            mode = "template"
        elif decision.outcome == "REFUSE":
            answer_text = decision.banner or "I'm unable to assist with this request. Please contact the appropriate team directly."
            mode = "template"
    done()

    # Scan output for leaked PHI
    if vault and not scan_output(answer_text, vault):
        logger.warning("PHI detected in output — replacing with redacted message")
        answer_text = "Response redacted for privacy. Please contact your supervisor."

    # ── Stage 7: Record ────────────────────────────────────────────────────────
    done = _tick("record")
    audit_id = None
    ticket_id_str = None

    try:
        audit_id, ticket_id_str = _record(
            session=session,
            user_id=user_id,
            dept_role=dept_role,
            sanitized_query=sanitized_query,
            intent=intent,
            decision=decision,
            evidence=evidence,
            verification=verification,
            answer_text=answer_text,
            mode=mode,
            idempotency_key=idempotency_key,
            conversation_id=conversation_id,
        )
    except Exception as e:
        logger.error("Record stage failed", error=str(e))
    done()

    # ── Assemble response ──────────────────────────────────────────────────────
    citations = [
        Citation(
            id=nid,
            title=node.get("title", nid),
            version=1,
        )
        for nid, node in evidence.nodes.items()
        if nid in evidence.entry_nodes
    ]

    confidence = Confidence(
        score=round(verification.get("score", 0.0), 4),
        band=verification.get("band", "low"),
        coverage=verification.get("coverage", {}),
        reasons=verification.get("reasons", []),
    )

    resp = ChatResponse(
        outcome=decision.outcome,
        text=answer_text,
        citations=citations,
        confidence=confidence,
        next_fields=decision.missing_fields,
        ticket=ticket_id_str,
        subgraph={"nodes": evidence.nodes, "edges": evidence.edges},
        mode=mode,
        banner=decision.banner,
        audit_id=audit_id,
    )

    return resp, stage_events


# ─── Record transaction ────────────────────────────────────────────────────────

def _to_uuid(val: Any) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return uuid.uuid4()
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(val))


def _record(
    session: Session,
    user_id: str,
    dept_role: str,
    sanitized_query: str,
    intent: QueryIntent,
    decision: Decision,
    evidence: EvidenceBundle,
    verification: dict,
    answer_text: str,
    mode: str,
    idempotency_key: Optional[str],
    conversation_id: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    """Write message + interaction + optional ticket + audit row in ONE transaction."""

    ticket_db = None
    ticket_id_str = None
    uid = _to_uuid(user_id)
    conv_id = _to_uuid(conversation_id)

    # Ensure conversation exists
    conv = session.get(Conversation, conv_id)
    if not conv:
        conv = Conversation(id=conv_id, user_id=uid)
        session.add(conv)
        session.flush()

    # Message row (redacted — store sanitized query)
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="user",
        content=sanitized_query[:4000],
    )
    session.add(msg)

    # Ticket row (if required)
    if decision.ticket and decision.outcome in ("ROUTE", "REFUSE"):
        ticket_db = Ticket(
            id=uuid.uuid4(),
            team=decision.team or "Operations",
            urgency=intent.urgency or "normal",
            reason=decision.reason,
            is_gap=decision.is_gap,
            status="open",
            opened_by=uid,
            summary=sanitized_query[:500],
            evidence_ids=[nid for nid in evidence.entry_nodes],
        )
        session.add(ticket_db)
        session.flush()
        ticket_id_str = str(ticket_db.id)

        event = TicketEvent(
            ticket_id=ticket_db.id,
            actor_id=uid,
            event_type="opened",
            data={"reason": decision.reason, "idempotency_key": idempotency_key},
        )
        session.add(event)

    # Interaction row
    interaction = Interaction(
        id=uuid.uuid4(),
        user_id=uid,
        dept_role=dept_role,
        outcome=decision.outcome,
        intent=intent.kind,
        workflow_id=intent.workflow_id,
        confidence=verification.get("score"),
        band=verification.get("band"),
        coverage_json=verification.get("coverage"),
        mode=mode,
        team=decision.team,
        is_gap=decision.is_gap,
    )
    session.add(interaction)
    session.flush()

    # Audit row
    audit_payload = {
        "who": user_id,
        "role": dept_role,
        "redacted_query": sanitized_query[:500],
        "node_ids": list(evidence.entry_nodes),
        "outcome": decision.outcome,
        "confidence": round(verification.get("score", 0.0), 4),
        "reason": decision.reason,
        "approver": None,
        "mode": mode,
    }
    audit_entry = write_audit_event(session, "chat", audit_payload)
    session.flush()
    session.commit()

    return audit_entry.id, ticket_id_str


# ─── Config/threshold loader ──────────────────────────────────────────────────

def _load_thresholds(session: Session) -> dict:
    from sqlalchemy import select as _select
    rows = session.execute(_select(PolicyThreshold)).scalars().all()
    config = {r.key: r.value for r in rows}
    # Also load string-typed settings (e.g. irreversible_actions)
    str_rows = session.execute(_select(SystemSetting)).scalars().all()
    for r in str_rows:
        if r.key not in config:
            config[r.key] = r.value
    return config


# ─── SSE event generator ──────────────────────────────────────────────────────

async def stream_pipeline(
    query: str,
    user_id: str,
    dept_role: str,
    session: Session,
    llm: LLMPort,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """
    Yield SSE events: stage notifications then final JSON result.
    Never streams unverified tokens.
    """
    stage_events_seen = []

    # We emit stage events via a callback wrapper
    # Run the full pipeline first (it's fast enough for SSE pre-emit)
    resp, stage_events = await run_pipeline(
        query=query,
        user_id=user_id,
        dept_role=dept_role,
        session=session,
        llm=llm,
        **kwargs,
    )

    for evt in stage_events:
        yield f"data: {json.dumps({'type': 'stage', 'text': evt})}\n\n"

    yield f"data: {json.dumps({'type': 'result', 'payload': resp.model_dump()})}\n\n"
    yield "data: [DONE]\n\n"
