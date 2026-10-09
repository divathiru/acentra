"""
Decision engine — PURE function, no I/O, no LLM.
The outcome is determined entirely by deterministic logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List

from app.knowledge.api import EvidenceBundle
from app.llm.understand import QueryIntent


# ─── Output ──────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    outcome: str                            # ANSWER | GUIDE | ROUTE | REFUSE
    reason: str = ""                        # Human-readable reason code
    team: Optional[str] = None             # Target team for ROUTE
    is_gap: bool = False                   # True if knowledge gap
    missing_fields: List[str] = field(default_factory=list)   # Fields to ask (GUIDE)
    draft: Optional[str] = None            # Draft answer for ROUTE with approval
    ticket: bool = False                   # Should a ticket be created?
    banner: Optional[str] = None           # UI banner text


# ─── Thresholds (read from DB via PolicyThreshold rows, defaults below) ───────

_DEFAULTS = {
    "approval_amount_threshold": 500.0,
    "irreversible_actions": "discharge_billing,specimen_rejection",
}


def _get(thresholds: dict, key: str):
    return thresholds.get(key, _DEFAULTS.get(key))


# ─── Pure decision function ───────────────────────────────────────────────────

def decide(
    guard_safe: bool,
    guard_clinical: bool,
    guard_injection: bool,
    evidence: EvidenceBundle,
    verification: dict,          # output of verify_evidence()
    intent: QueryIntent,
    thresholds: dict,
    workflow_slots: dict,        # currently collected slots
    required_fields: list[str],  # required fields for this step
) -> Decision:
    """
    Deterministic decision engine. No I/O. No LLM.
    Returns Decision with ONE of: ANSWER, GUIDE, ROUTE, REFUSE.

    Branch order (first match wins):
    1. Guard unsafe   → REFUSE
    2. Evidence conflict → ROUTE (source_conflict)
    3. Sensitive report → ROUTE (no ticket)
    4. Low evidence band → ROUTE (insufficient_evidence, is_gap=True)
    5. Workflow intent:
       a. Missing required fields → GUIDE
       b. Approval / irreversible → ROUTE (approval)
       c. Next step available → GUIDE
    6. Else → ANSWER
    """

    # ── Branch 1: Guard blocked ────────────────────────────────────────────────
    if not guard_safe:
        reason = "clinical_question" if guard_clinical else ("injection_attempt" if guard_injection else "safety_block")
        return Decision(
            outcome="REFUSE",
            reason=reason,
            banner="This question requires clinical expertise. Please contact the appropriate clinical team.",
        )

    # ── Branch 2: Knowledge conflict ───────────────────────────────────────────
    if evidence.conflict_flag:
        owners = evidence.conflict_owners
        team = owners[0] if owners else "Document Review Team"
        return Decision(
            outcome="ROUTE",
            reason="source_conflict",
            team=team,
            ticket=True,
            banner="Conflicting guidance found in approved sources. Routing to document owners for resolution.",
        )

    # ── Branch 3: Sensitive report ─────────────────────────────────────────────
    if intent.kind == "sensitive_report":
        return Decision(
            outcome="ROUTE",
            reason="sensitive_report",
            team="Compliance & HR",
            ticket=False,  # Audit stores category only — no ticket per spec
            banner="This report has been securely recorded. A compliance team member will follow up.",
        )

    # ── Branch 4: Insufficient evidence ───────────────────────────────────────
    band = verification.get("band", "low")
    if band == "low":
        # Determine owning team from evidence nodes or fall back
        owning_team = _extract_owning_team(evidence) or "Department Operations Head"
        return Decision(
            outcome="ROUTE",
            reason="insufficient_evidence",
            team=owning_team,
            is_gap=True,
            ticket=True,
            banner="I couldn't find a confident answer. This has been flagged as a knowledge gap and routed to the right team.",
        )

    # ── Branch 5: Workflow intent ──────────────────────────────────────────────
    if intent.kind in ("start_workflow", "workflow_reply"):

        # 5a. Missing required fields → ask up to 2
        missing = [f for f in required_fields if f not in workflow_slots or not workflow_slots[f]]
        if missing:
            ask = missing[:2]  # ask at most 2 at a time
            return Decision(
                outcome="GUIDE",
                reason="missing_fields",
                missing_fields=ask,
            )

        # 5b. Approval threshold or irreversible workflow → ROUTE for approval
        irreversible = {s.strip() for s in str(_get(thresholds, "irreversible_actions")).split(",")}
        wf_id = intent.workflow_id or ""
        amount = float(workflow_slots.get("amount", 0) or 0)
        approval_threshold = float(_get(thresholds, "approval_amount_threshold"))

        if wf_id in irreversible or amount >= approval_threshold:
            return Decision(
                outcome="ROUTE",
                reason="approval_required",
                team="Supervisor",
                ticket=True,
                draft=f"Workflow '{wf_id}' requires supervisor approval. Slots collected: {workflow_slots}",
                banner="This action requires supervisor approval. A draft has been submitted.",
            )

        # 5c. Guide to the next step
        return Decision(
            outcome="GUIDE",
            reason="next_step",
        )

    # ── Branch 6: ANSWER ──────────────────────────────────────────────────────
    return Decision(outcome="ANSWER")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_owning_team(evidence: EvidenceBundle) -> Optional[str]:
    """Return the owner of the first entry node in the evidence bundle."""
    for nid in evidence.entry_nodes:
        node = evidence.nodes.get(nid)
        if node and node.get("owner"):
            return node["owner"]
    return None
