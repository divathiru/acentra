"""
Public API for the workflow module.

Orchestrates: load FSM → load/create session → run scenario handler → return action.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from app.core.models import GraphVersion, WorkflowSession
from app.workflow.fsm import (
    WorkflowDef,
    advance_fsm,
    load_workflow,
    _slugify,
    validate_slots,
    _is_sensitive,
)
from app.workflow.session_store import SessionStore
from app.workflow.scenarios.mri_preauth import WorkflowAction, handle_mri_preauth, MRI_SENSITIVE_FIELDS
from app.workflow.scenarios.discharge_billing import handle_discharge_billing
from app.workflow.scenarios.specimen_rejection import handle_specimen_rejection

logger = structlog.get_logger(__name__)


# ─── Workflow keys ────────────────────────────────────────────────────────────
WORKFLOW_MRI = "mri_pre_authorization"
WORKFLOW_DISCHARGE = "discharge_billing_clearance"
WORKFLOW_SPECIMEN = "specimen_rejection_and_resubmission"

# Map of scenario names to handler functions and sensitive field sets
_SCENARIO_HANDLERS = {
    WORKFLOW_MRI: (handle_mri_preauth, MRI_SENSITIVE_FIELDS),
    WORKFLOW_DISCHARGE: (handle_discharge_billing, frozenset()),
    WORKFLOW_SPECIMEN: (handle_specimen_rejection, frozenset()),
}

# Default threshold for billing supervisor approval
_DEFAULT_BILLING_THRESHOLD = 5000.0


def _get_active_version_id(db: Session) -> str:
    row = db.execute(
        __import__("sqlalchemy").select(GraphVersion.id).where(GraphVersion.status == "active")
    ).scalar_one_or_none()
    if not row:
        raise RuntimeError("No active graph version found")
    return str(row)


def run_workflow(
    workflow_id: str,
    user_id: str,
    dept: str,
    new_slots: Dict[str, Any],
    db: Session,
    thresholds: Dict[str, float],
    encounter_id: Optional[str] = None,
) -> Tuple[WorkflowAction, Dict[str, Any]]:
    """
    Main entry point for workflow processing.

    Returns (action, public_slots) where public_slots never contains sensitive values.
    """
    encounter_id = encounter_id or "default"
    version_id = _get_active_version_id(db)
    store = SessionStore(db)

    # Load or create session
    sess, created = store.get_or_create(
        user_id=user_id,
        workflow_id=workflow_id,
        encounter_id=encounter_id,
        dept=dept,
    )
    logger.info("workflow.session", workflow_id=workflow_id, created=created, session_id=str(sess.id))

    # Identify sensitive fields for this workflow
    _, sensitive_fields = _SCENARIO_HANDLERS.get(workflow_id, (None, frozenset()))

    # Separate incoming slots into sensitive and plain
    sensitive_new = {k: v for k, v in new_slots.items() if k in sensitive_fields or _is_sensitive(k)}
    plain_new = {k: v for k, v in new_slots.items() if k not in sensitive_new}

    # Validate incoming plain slots first
    wf_def = load_workflow(db, workflow_id, version_id)
    if wf_def and plain_new:
        validation = validate_slots(wf_def, plain_new)
        if not validation.ok:
            return WorkflowAction(
                state="COLLECT",
                text=(
                    "Some values provided need correction:\n"
                    + "\n".join(f"- **{k}**: {v}" for k, v in validation.errors.items())
                ),
                prompt_fields=list(validation.errors.keys()),
            ), store.get_slots(sess)

    # Merge slots into session (sensitive → vault, rest → slots_json)
    all_new = {**plain_new, **sensitive_new}
    if all_new:
        store.set_slots(sess, all_new, sensitive_field_names=set(sensitive_new.keys()))

    # Check for article version drift (warn but continue)
    if wf_def and wf_def.governing_article_version:
        drift = store.check_article_version_drift(sess, wf_def.governing_article_version)
        if drift:
            logger.warning(
                "workflow.article_version_drift",
                pinned=sess.article_version,
                current=wf_def.governing_article_version,
            )

    current_slots = store.get_slots(sess)
    vault_keys = store.get_vault_keys(sess)

    # Dispatch to scenario handler
    governing_article_id = wf_def.governing_article_id if wf_def else None

    handler_fn, _ = _SCENARIO_HANDLERS.get(workflow_id, (None, None))
    if not handler_fn:
        # Generic FSM fallback
        if not wf_def:
            return WorkflowAction(
                state="ROUTE",
                text="Unknown workflow — routing to Operations for manual handling.",
                route_team="Operations",
                route_reason="unknown_workflow",
            ), current_slots

        fsm_result = advance_fsm(wf_def, current_slots, vault_keys, thresholds)
        if fsm_result.state == "COLLECT":
            return WorkflowAction(
                state="COLLECT",
                text=f"To continue, I need: {', '.join(fsm_result.prompt_fields)}",
                prompt_fields=fsm_result.prompt_fields,
            ), current_slots
        elif fsm_result.state == "GATE":
            return WorkflowAction(
                state="DONE",
                text=f"Workflow complete.\n\n{fsm_result.summary}",
            ), current_slots

    # Route to specific scenario handler
    action: WorkflowAction
    if workflow_id == WORKFLOW_MRI:
        action = handle_mri_preauth(current_slots, vault_keys, governing_article_id)
    elif workflow_id == WORKFLOW_DISCHARGE:
        action = handle_discharge_billing(current_slots, vault_keys, thresholds, governing_article_id)
    elif workflow_id == WORKFLOW_SPECIMEN:
        action = handle_specimen_rejection(current_slots, vault_keys, governing_article_id)
    else:
        action = WorkflowAction(
            state="ROUTE",
            text="Routing to the appropriate team for this workflow.",
            route_team="Operations",
        )

    # Purge session if workflow is done
    if action.state in ("DONE", "ROUTE"):
        store.purge(sess)
        logger.info("workflow.session_purged", workflow_id=workflow_id, state=action.state)

    return action, current_slots


def identify_workflow(intent_workflow_id: Optional[str], query: str) -> Optional[str]:
    """
    Map an intent workflow_id (from LLM understand) to a known workflow key.
    Falls back to keyword matching.
    """
    if intent_workflow_id:
        slug = _slugify(intent_workflow_id)
        for k in _SCENARIO_HANDLERS:
            if slug == k or slug in k or k in slug:
                return k

    # Keyword matching fallback
    q = query.lower()
    if any(t in q for t in ["mri", "pre-auth", "preauth", "pre authorization", "mri authorization"]):
        return WORKFLOW_MRI
    if any(t in q for t in ["discharge billing", "billing clearance", "discharge clearance"]):
        return WORKFLOW_DISCHARGE
    if any(t in q for t in ["specimen", "lab rejection", "specimen rejection", "resubmit specimen"]):
        return WORKFLOW_SPECIMEN

    return None
