"""
Public interface for the analytics module.

Computes real-time system metrics from Interaction, Ticket, and AuditLog tables.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from app.core.models import Interaction, Ticket

logger = structlog.get_logger(__name__)


def get_analytics_summary(db: Session) -> Dict[str, Any]:
    """
    Compute comprehensive analytics summary:
    - total_interactions
    - outcome_breakdown
    - confidence_band_breakdown
    - mode_breakdown (llm vs template)
    - gap_rate (% of queries resulting in ticket/gap)
    - ticket_volume_by_team
    - average_latency_ms
    - stage_latency_averages
    - citation_validity_rate
    - deflection_rate
    - route_rate
    - refuse_rate
    - route_reasons
    - open_tickets
    - overdue_tickets
    - knowledge_gap_count
    - feedback_helpful_rate
    - queries_per_day
    - top_intents
    - top_workflows
    - queries_by_dept_role
    """
    total = db.execute(select(func.count(Interaction.id))).scalar() or 0

    if total == 0:
        return {
            "total_interactions": 0,
            "outcome_breakdown": {},
            "confidence_band_breakdown": {},
            "mode_breakdown": {},
            "gap_rate": 0.0,
            "knowledge_gap_count": 0,
            "ticket_volume_by_team": {},
            "average_latency_ms": 0,
            "stage_latency_averages": {},
            "citation_validity_rate": 0.0,
            "deflection_rate": 0.0,
            "route_rate": 0.0,
            "refuse_rate": 0.0,
            "route_reasons": {},
            "open_tickets": 0,
            "overdue_tickets": 0,
            "feedback_helpful_rate": 0.0,
            "queries_per_day": {},
            "top_intents": {},
            "top_workflows": {},
            "queries_by_dept_role": {},
            "p50_latency_llm": 0,
            "p95_latency_llm": 0,
            "p50_latency_template": 0,
            "p95_latency_template": 0,
        }

    # Outcomes
    outcomes_raw = db.execute(
        select(Interaction.outcome, func.count(Interaction.id))
        .group_by(Interaction.outcome)
    ).all()
    outcome_breakdown = {str(o): c for o, c in outcomes_raw}

    # Confidence bands
    bands_raw = db.execute(
        select(Interaction.band, func.count(Interaction.id))
        .group_by(Interaction.band)
    ).all()
    confidence_band_breakdown = {str(b or "UNKNOWN"): c for b, c in bands_raw}

    # Mode breakdown
    mode_raw = db.execute(
        select(Interaction.mode, func.count(Interaction.id))
        .group_by(Interaction.mode)
    ).all()
    mode_breakdown = {str(m or "template"): c for m, c in mode_raw}

    # Gap rate
    gaps_count = db.execute(
        select(func.count(Interaction.id)).where(Interaction.is_gap == True)
    ).scalar() or 0
    gap_rate = round((gaps_count / total) * 100, 2) if total > 0 else 0.0

    # Ticket volume by team
    tickets_raw = db.execute(
        select(Ticket.team, func.count(Ticket.id))
        .group_by(Ticket.team)
    ).all()
    ticket_volume_by_team = {str(t or "Unassigned"): c for t, c in tickets_raw}

    # Deflection rate (ANSWER + GUIDE)
    deflected_count = db.execute(
        select(func.count(Interaction.id)).where(Interaction.outcome.in_(["ANSWER", "GUIDE"]))
    ).scalar() or 0
    deflection_rate = round((deflected_count / total) * 100, 2) if total > 0 else 0.0

    # ROUTE rate and REFUSE rate
    route_count = outcome_breakdown.get("ROUTE", 0)
    route_rate = round((route_count / total) * 100, 2) if total > 0 else 0.0
    
    refuse_count = outcome_breakdown.get("REFUSE", 0)
    refuse_rate = round((refuse_count / total) * 100, 2) if total > 0 else 0.0
    
    # ROUTE reasons (top intents that lead to ROUTE)
    route_reasons_raw = db.execute(
        select(Interaction.intent, func.count(Interaction.id))
        .where(Interaction.outcome == "ROUTE")
        .group_by(Interaction.intent)
    ).all()
    route_reasons = {str(i or "UNKNOWN"): c for i, c in route_reasons_raw}

    # Citation validity rate
    citations_total = db.execute(select(func.count(Interaction.id)).where(Interaction.citation_ok.is_not(None))).scalar() or 0
    citations_ok = db.execute(select(func.count(Interaction.id)).where(Interaction.citation_ok == True)).scalar() or 0
    citation_validity_rate = round((citations_ok / citations_total) * 100, 2) if citations_total > 0 else 0.0

    # Open tickets and overdue tickets (assume > 3 days is overdue)
    from datetime import datetime, timedelta
    open_statuses = ["open", "in_progress"]
    open_tickets = db.execute(
        select(func.count(Ticket.id)).where(Ticket.status.in_(open_statuses))
    ).scalar() or 0
    
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    overdue_tickets = db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.status.in_(open_statuses),
            Ticket.created_at < three_days_ago
        )
    ).scalar() or 0
    
    # Feedback helpful rate
    feedback_total = db.execute(select(func.count(Interaction.id)).where(Interaction.feedback.is_not(None))).scalar() or 0
    feedback_positive = db.execute(select(func.count(Interaction.id)).where(Interaction.feedback == "positive")).scalar() or 0
    feedback_helpful_rate = round((feedback_positive / feedback_total) * 100, 2) if feedback_total > 0 else 0.0
    
    # Queries per day (last 30 days)
    # Using cast to Date for postgres
    from sqlalchemy import cast, Date
    queries_per_day_raw = db.execute(
        select(cast(Interaction.ts, Date), func.count(Interaction.id))
        .group_by(cast(Interaction.ts, Date))
        .order_by(cast(Interaction.ts, Date))
    ).all()
    queries_per_day = {str(d): c for d, c in queries_per_day_raw}
    
    # Top intents and workflows
    intents_raw = db.execute(
        select(Interaction.intent, func.count(Interaction.id))
        .group_by(Interaction.intent)
        .order_by(func.count(Interaction.id).desc())
        .limit(10)
    ).all()
    top_intents = {str(i or "UNKNOWN"): c for i, c in intents_raw}
    
    workflows_raw = db.execute(
        select(Interaction.workflow_id, func.count(Interaction.id))
        .where(Interaction.workflow_id.is_not(None))
        .group_by(Interaction.workflow_id)
        .order_by(func.count(Interaction.id).desc())
        .limit(10)
    ).all()
    top_workflows = {str(w): c for w, c in workflows_raw}
    
    # Queries by dept role
    dept_roles_raw = db.execute(
        select(Interaction.dept_role, func.count(Interaction.id))
        .group_by(Interaction.dept_role)
    ).all()
    queries_by_dept_role = {str(r or "UNKNOWN"): c for r, c in dept_roles_raw}

    # Percentile latencies using percentile_cont in postgres
    p50_llm = 0
    p95_llm = 0
    p50_template = 0
    p95_template = 0
    try:
        res_llm = db.execute(text("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM interactions WHERE mode='llm'")).first()
        if res_llm:
            p50_llm = float(res_llm[0] or 0)
            p95_llm = float(res_llm[1] or 0)
            
        res_tpl = db.execute(text("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM interactions WHERE mode='template'")).first()
        if res_tpl:
            p50_template = float(res_tpl[0] or 0)
            p95_template = float(res_tpl[1] or 0)
    except Exception:
        pass

    # Latencies
    avg_latency = db.execute(select(func.avg(Interaction.latency_ms))).scalar() or 0.0

    # Stage latencies aggregation from stage_ms_json
    stage_latencies: Dict[str, float] = {}
    interactions_with_stages = db.execute(
        select(Interaction.stage_ms_json).where(Interaction.stage_ms_json.is_not(None))
    ).scalars().all()

    if interactions_with_stages:
        totals: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for stage_dict in interactions_with_stages:
            if isinstance(stage_dict, dict):
                for k, v in stage_dict.items():
                    if isinstance(v, (int, float)):
                        totals[k] = totals.get(k, 0.0) + float(v)
                        counts[k] = counts.get(k, 0) + 1
        for k in totals:
            stage_latencies[k] = round(totals[k] / counts[k], 2)

    return {
        "total_interactions": total,
        "outcome_breakdown": outcome_breakdown,
        "confidence_band_breakdown": confidence_band_breakdown,
        "mode_breakdown": mode_breakdown,
        "gap_rate": gap_rate,
        "knowledge_gap_count": gaps_count,
        "ticket_volume_by_team": ticket_volume_by_team,
        "average_latency_ms": round(float(avg_latency), 2),
        "stage_latency_averages": stage_latencies,
        "citation_validity_rate": citation_validity_rate,
        "deflection_rate": deflection_rate,
        "route_rate": route_rate,
        "refuse_rate": refuse_rate,
        "route_reasons": route_reasons,
        "open_tickets": open_tickets,
        "overdue_tickets": overdue_tickets,
        "feedback_helpful_rate": feedback_helpful_rate,
        "queries_per_day": queries_per_day,
        "top_intents": top_intents,
        "top_workflows": top_workflows,
        "queries_by_dept_role": queries_by_dept_role,
        "p50_latency_llm": p50_llm,
        "p95_latency_llm": p95_llm,
        "p50_latency_template": p50_template,
        "p95_latency_template": p95_template,
    }
