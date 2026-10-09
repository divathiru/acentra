"""
Decision table tests — 100% branch coverage on decide().
Each test exercises exactly one branch path.
"""
from __future__ import annotations

import pytest
from app.orchestrator.decide import decide, Decision
from app.knowledge.api import EvidenceBundle
from app.llm.understand import QueryIntent, QueryEntities


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def _empty_bundle(**overrides) -> EvidenceBundle:
    defaults = dict(
        nodes={},
        edges=[],
        entry_nodes=[],
        rrf_scores={},
        top1_cosine=0.0,
        conflict_flag=False,
        conflict_owners=[],
        superseded_notes={},
    )
    defaults.update(overrides)
    return EvidenceBundle(**defaults)


def _intent(kind="knowledge_question", **kw) -> QueryIntent:
    return QueryIntent(kind=kind, **kw)


def _verif(band="high") -> dict:
    return {
        "score": {"high": 0.8, "medium": 0.55, "low": 0.2}[band],
        "band": band,
        "conflict": False,
        "coverage": {"WHAT": True, "WHERE": True, "NEXT": True, "WHO": True, "HOW": True},
        "reasons": [],
    }


_THRESHOLDS = {
    "approval_amount_threshold": 500.0,
    "irreversible_actions": "discharge_billing,specimen_rejection",
}


def _decide(guard_safe=True, guard_clinical=False, guard_injection=False,
            evidence=None, verification=None, intent=None,
            thresholds=None, workflow_slots=None, required_fields=None):
    return decide(
        guard_safe=guard_safe,
        guard_clinical=guard_clinical,
        guard_injection=guard_injection,
        evidence=evidence or _empty_bundle(),
        verification=verification or _verif("high"),
        intent=intent or _intent(),
        thresholds=thresholds or _THRESHOLDS,
        workflow_slots=workflow_slots or {},
        required_fields=required_fields or [],
    )


# ─── Branch 1: Guard unsafe → REFUSE ─────────────────────────────────────────

def test_branch_1a_clinical_refuse():
    d = _decide(guard_safe=False, guard_clinical=True)
    assert d.outcome == "REFUSE"
    assert d.reason == "clinical_question"


def test_branch_1b_injection_refuse():
    d = _decide(guard_safe=False, guard_injection=True, guard_clinical=False)
    assert d.outcome == "REFUSE"
    assert d.reason == "injection_attempt"


def test_branch_1c_generic_safety_refuse():
    d = _decide(guard_safe=False, guard_clinical=False, guard_injection=False)
    assert d.outcome == "REFUSE"
    assert d.reason == "safety_block"


# ─── Branch 2: Conflict → ROUTE ───────────────────────────────────────────────

def test_branch_2_conflict_route():
    bundle = _empty_bundle(conflict_flag=True, conflict_owners=["Radiology Billing"])
    d = _decide(evidence=bundle)
    assert d.outcome == "ROUTE"
    assert d.reason == "source_conflict"
    assert d.team == "Radiology Billing"
    assert d.ticket is True


def test_branch_2_conflict_no_owners_fallback_team():
    bundle = _empty_bundle(conflict_flag=True, conflict_owners=[])
    d = _decide(evidence=bundle)
    assert d.outcome == "ROUTE"
    assert d.team == "Document Review Team"


# ─── Branch 3: Sensitive report → ROUTE (no ticket) ──────────────────────────

def test_branch_3_sensitive_report_no_ticket():
    d = _decide(intent=_intent("sensitive_report"))
    assert d.outcome == "ROUTE"
    assert d.reason == "sensitive_report"
    assert d.ticket is False  # No ticket per spec
    assert d.team == "Compliance & HR"


# ─── Branch 4: Low band → ROUTE (is_gap) ─────────────────────────────────────

def test_branch_4_low_band_route_gap():
    d = _decide(verification=_verif("low"))
    assert d.outcome == "ROUTE"
    assert d.reason == "insufficient_evidence"
    assert d.is_gap is True
    assert d.ticket is True


def test_branch_4_low_band_owning_team_from_evidence():
    bundle = _empty_bundle(
        nodes={"n1": {"id": "n1", "type": "article", "title": "Policy", "body": "Body", "owner": "Radiology"}},
        entry_nodes=["n1"],
    )
    d = _decide(evidence=bundle, verification=_verif("low"))
    assert d.team == "Radiology"


def test_branch_4_low_band_fallback_team_when_no_owner():
    d = _decide(verification=_verif("low"), evidence=_empty_bundle())
    assert d.team == "Department Operations Head"


# ─── Branch 5a: Workflow + missing fields → GUIDE ────────────────────────────

def test_branch_5a_workflow_missing_fields_guide():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),
        required_fields=["patient_id", "insurer", "procedure_date"],
        workflow_slots={},
    )
    assert d.outcome == "GUIDE"
    assert d.reason == "missing_fields"
    assert len(d.missing_fields) <= 2
    assert "patient_id" in d.missing_fields


def test_branch_5a_asks_at_most_2_fields():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),
        required_fields=["field_a", "field_b", "field_c"],
        workflow_slots={},
    )
    assert len(d.missing_fields) == 2


def test_branch_5a_partially_filled_slots():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),
        required_fields=["patient_id", "insurer"],
        workflow_slots={"patient_id": "12345"},
    )
    assert d.outcome == "GUIDE"
    assert "insurer" in d.missing_fields
    assert "patient_id" not in d.missing_fields


# ─── Branch 5b: Irreversible workflow → ROUTE (approval) ─────────────────────

def test_branch_5b_irreversible_workflow_route():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="discharge_billing"),
        workflow_slots={"patient_id": "12345", "insurer": "Aetna"},
        required_fields=["patient_id", "insurer"],
    )
    assert d.outcome == "ROUTE"
    assert d.reason == "approval_required"
    assert d.ticket is True
    assert d.team == "Supervisor"


def test_branch_5b_amount_above_threshold_route():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),  # not inherently irreversible
        workflow_slots={"patient_id": "12345", "insurer": "Aetna", "amount": "750"},
        required_fields=["patient_id", "insurer"],
    )
    assert d.outcome == "ROUTE"
    assert d.reason == "approval_required"


def test_branch_5b_amount_below_threshold_guide():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),
        workflow_slots={"patient_id": "12345", "insurer": "Aetna", "amount": "100"},
        required_fields=["patient_id", "insurer"],
    )
    assert d.outcome == "GUIDE"
    assert d.reason == "next_step"


# ─── Branch 5c: Workflow, fields filled, non-irreversible → GUIDE (next step) ──

def test_branch_5c_workflow_reply_next_step():
    d = _decide(
        intent=_intent("workflow_reply", workflow_id="it_his_access"),
        workflow_slots={"employee_id": "E001", "system": "HIS"},
        required_fields=["employee_id", "system"],
    )
    assert d.outcome == "GUIDE"
    assert d.reason == "next_step"


# ─── Branch 6: ANSWER ─────────────────────────────────────────────────────────

def test_branch_6_answer_knowledge_question():
    d = _decide(
        intent=_intent("knowledge_question"),
        verification=_verif("high"),
    )
    assert d.outcome == "ANSWER"


def test_branch_6_answer_status_check():
    d = _decide(
        intent=_intent("status_check"),
        verification=_verif("high"),
    )
    assert d.outcome == "ANSWER"


def test_branch_6_answer_complaint_high_band():
    d = _decide(
        intent=_intent("complaint"),
        verification=_verif("high"),
    )
    assert d.outcome == "ANSWER"


def test_branch_6_answer_medium_band():
    """Medium band still ANSWERs — generate will add uncertainty notice."""
    d = _decide(
        intent=_intent("knowledge_question"),
        verification=_verif("medium"),
    )
    assert d.outcome == "ANSWER"


# ─── Guard takes priority over all other branches ────────────────────────────

def test_guard_overrides_conflict():
    """Guard unsafe takes priority even when evidence has a conflict."""
    bundle = _empty_bundle(conflict_flag=True, conflict_owners=["Team A"])
    d = _decide(guard_safe=False, guard_clinical=True, evidence=bundle)
    assert d.outcome == "REFUSE"


def test_guard_overrides_sensitive_report():
    d = _decide(guard_safe=False, guard_injection=True, intent=_intent("sensitive_report"))
    assert d.outcome == "REFUSE"


# ─── Conflict takes priority over sensitive_report ────────────────────────────

def test_conflict_overrides_sensitive_report():
    bundle = _empty_bundle(conflict_flag=True, conflict_owners=["Team X"])
    d = _decide(intent=_intent("sensitive_report"), evidence=bundle)
    assert d.outcome == "ROUTE"
    assert d.reason == "source_conflict"


# ─── Low band takes priority over workflow ─────────────────────────────────────

def test_low_band_overrides_workflow():
    d = _decide(
        intent=_intent("start_workflow", workflow_id="mri_preauth"),
        verification=_verif("low"),
    )
    assert d.outcome == "ROUTE"
    assert d.reason == "insufficient_evidence"
