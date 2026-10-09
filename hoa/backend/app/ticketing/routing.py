"""
Deterministic routing rules engine.

The LLM only supplies issue_type. All routing decisions are determined by
the routing_rules table + an always-route list.

Always-routed categories:
- account-specific data (any question about a specific patient's account)
- clinical advice
- sensitive reports
- access approval requests
- refunds and financial corrections
- unclear or low-confidence queries
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import RoutingRule

logger = structlog.get_logger(__name__)


# ─── Always-route intents ────────────────────────────────────────────────────
_ALWAYS_ROUTE_INTENTS = frozenset({
    "account_specific",
    "clinical",
    "sensitive_report",
    "access_approval",
    "refund_request",
    "financial_correction",
    "unclear",
    "complaint_formal",
})

_ALWAYS_ROUTE_KEYWORDS = [
    # Account-specific
    "my account", "patient account", "specific claim", "account balance",
    # Clinical
    "diagnose", "diagnosis", "treatment plan", "prescribe", "medication dosage",
    "drug interaction", "clinical decision",
    # Financial corrections
    "refund", "correction", "billing error", "overcharge", "credit",
    "chargeback", "billing dispute",
    # Access approvals
    "access request", "grant access", "add user", "system access",
]

_DEFAULT_ROUTING_TABLE: List[Dict[str, Any]] = [
    # Intent → team, urgency
    {"intent": "authorization_rejected",   "team": "Insurance/TPA",          "urgency": "urgent"},
    {"intent": "authorization_pending",    "team": "Insurance/TPA",          "urgency": "normal"},
    {"intent": "billing_correction",       "team": "Billing Supervisor",      "urgency": "high"},
    {"intent": "refund_request",           "team": "Billing Supervisor",      "urgency": "high"},
    {"intent": "clinical",                 "team": "Clinical Team",           "urgency": "urgent"},
    {"intent": "access_approval",          "team": "IT",                      "urgency": "normal"},
    {"intent": "sensitive_report",         "team": "Compliance",              "urgency": "high"},
    {"intent": "complaint_formal",         "team": "Patient Relations",       "urgency": "high"},
    {"intent": "account_specific",         "team": "Department Operations Head", "urgency": "normal"},
    {"intent": "unclear",                  "team": "Department Operations Head", "urgency": "normal"},
    {"intent": "low_confidence",           "team": "Department Operations Head", "urgency": "normal"},
    {"intent": "financial_correction",     "team": "Billing Supervisor",      "urgency": "high"},
    {"intent": "unknown_insurer",          "team": "Insurance/TPA",           "urgency": "normal"},
    {"intent": "specimen_rejection",       "team": "Laboratory",              "urgency": "normal"},
    {"intent": "it_access",               "team": "IT",                      "urgency": "normal"},
    {"intent": "discharge_billing",        "team": "Billing",                 "urgency": "normal"},
    {"intent": "mri_pre_auth",             "team": "Insurance/TPA",           "urgency": "normal"},
    # Fallback
    {"intent": "default",                  "team": "Department Operations Head", "urgency": "normal"},
]


class RoutingEngine:
    """
    Deterministic routing engine.
    Loads rules from DB; falls back to defaults if table is empty.
    """

    def __init__(self, db: Session):
        self.db = db
        self._rules: List[Dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self) -> None:
        db_rules = self.db.execute(
            select(RoutingRule).where(RoutingRule.active == True)
        ).scalars().all()

        if db_rules:
            self._rules = [
                {"intent": r.intent, "team": r.team, "urgency": r.urgency,
                 "condition": r.condition_json}
                for r in db_rules
            ]
        else:
            # Use defaults (no DB rules seeded yet)
            self._rules = _DEFAULT_ROUTING_TABLE

    def should_always_route(self, intent_kind: str, query: str) -> bool:
        """Return True if this query should always be routed to a human."""
        if intent_kind in _ALWAYS_ROUTE_INTENTS:
            return True
        q = query.lower()
        return any(kw in q for kw in _ALWAYS_ROUTE_KEYWORDS)

    def resolve_team(self, issue_type: str, dept_role: Optional[str] = None) -> Dict[str, str]:
        """
        Map an issue_type to {team, urgency}.
        The LLM supplies issue_type; the rest is deterministic.
        """
        normalized = issue_type.lower().replace(" ", "_").replace("-", "_")

        for rule in self._rules:
            rule_intent = rule["intent"].lower().replace(" ", "_")
            if rule_intent == normalized or normalized.startswith(rule_intent):
                return {"team": rule["team"], "urgency": rule.get("urgency", "normal")}

        # Check keyword matches
        for rule in self._rules:
            if rule["intent"].lower() in normalized:
                return {"team": rule["team"], "urgency": rule.get("urgency", "normal")}

        # Fallback
        return {"team": "Department Operations Head", "urgency": "normal"}

    def get_all_rules(self) -> List[Dict[str, Any]]:
        return self._rules


def seed_routing_rules(db: Session) -> None:
    """Seed default routing rules into the DB if the table is empty."""
    existing = db.execute(select(RoutingRule)).scalars().first()
    if existing:
        return

    for rule in _DEFAULT_ROUTING_TABLE:
        db.add(RoutingRule(
            intent=rule["intent"],
            team=rule["team"],
            urgency=rule.get("urgency", "normal"),
            condition_json=rule.get("condition"),
            active=True,
        ))
    db.commit()
    logger.info("routing.rules_seeded", count=len(_DEFAULT_ROUTING_TABLE))
