"""
Workflow FSM — generated from graph knowledge.

Loads workflow definitions from the knowledge graph (nodes: workflow, step, field,
form, system, team) and drives a simple slot-filling state machine:

  COLLECT → VALIDATE → GATE → (ROUTE | DONE)

The FSM is stateless; state lives in WorkflowSession.slots_json + vault.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.models import Edge, FieldDefinition, Node

logger = structlog.get_logger(__name__)


# ─── Workflow definition (loaded from DB once per request) ────────────────────

@dataclass
class FieldSpec:
    name: str
    field_type: str        # text | enum | date | regex | number
    required: bool
    allowed_values: List[str] = field(default_factory=list)
    validation_regex: Optional[str] = None
    sensitive: bool = False   # stored in vault, not slots_json


@dataclass
class StepDef:
    title: str
    body: str
    fields: List[FieldSpec] = field(default_factory=list)
    system: Optional[str] = None
    form: Optional[str] = None
    order: int = 0


@dataclass
class WorkflowDef:
    workflow_id: str          # e.g. "mri_pre_auth"
    title: str
    steps: List[StepDef]
    owning_team: Optional[str] = None
    escalation_team: Optional[str] = None
    governing_article_id: Optional[str] = None
    governing_article_version: Optional[int] = None
    form: Optional[str] = None
    system: Optional[str] = None

    @property
    def all_required_fields(self) -> List[str]:
        seen: set = set()
        result: List[str] = []
        for s in self.steps:
            for f in s.fields:
                if f.required and f.name not in seen:
                    seen.add(f.name)
                    result.append(f.name)
        return result

    def get_field_spec(self, name: str) -> Optional[FieldSpec]:
        for s in self.steps:
            for f in s.fields:
                if f.name == name:
                    return f
        return None

    def current_step(self, collected_fields: set) -> Optional[StepDef]:
        """Return the first step that still has uncollected required fields."""
        for step in self.steps:
            missing = [f for f in step.fields if f.required and f.name not in collected_fields]
            if missing:
                return step
        return None  # All steps complete


# ─── SENSITIVE fields (never stored in slots_json) ──────────────────────────
_SENSITIVE_FIELD_PATTERNS = frozenset({"mrn", "patient_mrn", "ssn", "dob", "date_of_birth"})


def _is_sensitive(name: str) -> bool:
    return any(p in name.lower() for p in _SENSITIVE_FIELD_PATTERNS)


# ─── Workflow slug normalization ──────────────────────────────────────────────

def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


# ─── DB loader ────────────────────────────────────────────────────────────────

_ALLOW_LIST_EDGE_TYPES = {"has_step", "requires", "requires_form", "defined_in",
                          "owned_by", "escalated_to", "governs", "uses_system"}


def load_workflow(session: Session, workflow_key: str, version_id: str) -> Optional[WorkflowDef]:
    """
    Load a WorkflowDef from the active knowledge graph.
    workflow_key is a slug like 'mri_pre_authorization' or 'discharge_billing_clearance'.
    """
    # Try exact title match first, then slug matching
    wf_node = session.execute(
        select(Node)
        .where(
            Node.type == "workflow",
            Node.version_id == version_id,
            Node.status == "approved",
        )
    ).scalars().all()

    matched: Optional[Node] = None
    for wn in wf_node:
        if _slugify(wn.title) == workflow_key or wn.title.lower() == workflow_key.lower():
            matched = wn
            break

    if not matched:
        # Fuzzy: check if workflow_key appears in the title slug
        for wn in wf_node:
            slug = _slugify(wn.title)
            key_parts = workflow_key.split("_")
            if all(p in slug for p in key_parts[:2]):
                matched = wn
                break

    if not matched:
        logger.warning("workflow.not_found", key=workflow_key)
        return None

    # Load steps (ordered by title for reproducibility; graph stores them unordered)
    step_edges = session.execute(
        select(Edge).where(
            Edge.from_id == matched.id,
            Edge.type == "has_step",
            Edge.version_id == version_id,
        )
    ).scalars().all()

    step_nodes: List[Node] = []
    for e in step_edges:
        sn = session.execute(
            select(Node).where(Node.id == e.to_id, Node.version_id == version_id)
        ).scalar_one_or_none()
        if sn and sn.type == "step":
            step_nodes.append(sn)

    # Sort steps: try to use a natural ordering embedded in body "Step N" prefix
    def _step_order(n: Node) -> int:
        m = re.search(r"step\s+(\d+)", n.body.lower() if n.body else "")
        return int(m.group(1)) if m else 999

    step_nodes.sort(key=_step_order)

    steps: List[StepDef] = []
    owning_team: Optional[str] = None
    escalation_team: Optional[str] = None
    governing_article_id: Optional[str] = None
    governing_article_version: Optional[int] = None
    wf_form: Optional[str] = None
    wf_system: Optional[str] = None

    # Get workflow-level metadata from edges
    wf_edges = session.execute(
        select(Edge).where(Edge.from_id == matched.id, Edge.version_id == version_id)
    ).scalars().all()

    for e in wf_edges:
        target = session.execute(
            select(Node).where(Node.id == e.to_id, Node.version_id == version_id)
        ).scalar_one_or_none()
        if not target:
            continue
        if target.type == "team" and e.type == "owned_by" and not owning_team:
            owning_team = target.title
        elif target.type == "team" and e.type == "escalated_to" and not escalation_team:
            escalation_team = target.title
        elif target.type == "article" and e.type in ("defined_in", "governs", "governed_by"):
            governing_article_id = str(target.id)
            governing_article_version = target.version
        elif target.type == "form" and not wf_form:
            wf_form = target.title
        elif target.type == "system" and not wf_system:
            wf_system = target.title

    for i, sn in enumerate(step_nodes):
        # Load fields for this step
        field_edges = session.execute(
            select(Edge).where(
                Edge.from_id == sn.id,
                Edge.type == "requires",
                Edge.version_id == version_id,
            )
        ).scalars().all()

        step_fields: List[FieldSpec] = []
        for fe in field_edges:
            fn = session.execute(
                select(Node).where(Node.id == fe.to_id, Node.version_id == version_id)
            ).scalar_one_or_none()
            if fn and fn.type == "field":
                # Infer type from body/name
                ftype = "text"
                allowed: List[str] = []
                regex: Optional[str] = None
                if fn.body:
                    btext = fn.body.lower()
                    if "date" in fn.title.lower() or "date" in btext:
                        ftype = "date"
                    elif "number" in btext or "amount" in btext or "charges" in btext:
                        ftype = "number"
                    elif "|" in fn.body or "enum" in btext:
                        ftype = "enum"
                        # Extract allowed values
                        for line in fn.body.split("\n"):
                            if "|" in line:
                                allowed = [v.strip() for v in line.split("|") if v.strip()]

                step_fields.append(FieldSpec(
                    name=fn.title,
                    field_type=ftype,
                    required=True,
                    allowed_values=allowed,
                    validation_regex=regex,
                    sensitive=_is_sensitive(fn.title),
                ))

        # Step metadata from edges
        step_system: Optional[str] = None
        step_form: Optional[str] = None
        s_edges = session.execute(
            select(Edge).where(Edge.from_id == sn.id, Edge.version_id == version_id)
        ).scalars().all()
        for se in s_edges:
            tn = session.execute(
                select(Node).where(Node.id == se.to_id, Node.version_id == version_id)
            ).scalar_one_or_none()
            if tn and tn.type == "system" and not step_system:
                step_system = tn.title
            elif tn and tn.type == "form" and not step_form:
                step_form = tn.title

        steps.append(StepDef(
            title=sn.title,
            body=sn.body or "",
            fields=step_fields,
            system=step_system or wf_system,
            form=step_form or wf_form,
            order=i,
        ))

    return WorkflowDef(
        workflow_id=_slugify(matched.title),
        title=matched.title,
        steps=steps,
        owning_team=owning_team,
        escalation_team=escalation_team,
        governing_article_id=governing_article_id,
        governing_article_version=governing_article_version,
        form=wf_form,
        system=wf_system,
    )


# ─── Slot validation ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    errors: Dict[str, str] = field(default_factory=dict)


def validate_slots(wf: WorkflowDef, slots: Dict[str, Any]) -> ValidationResult:
    """Validate all provided slots against their field specs."""
    errors: Dict[str, str] = {}
    for field_name, value in slots.items():
        spec = wf.get_field_spec(field_name)
        if not spec:
            continue
        err = _validate_one(spec, value)
        if err:
            errors[field_name] = err
    return ValidationResult(ok=len(errors) == 0, errors=errors)


def _validate_one(spec: FieldSpec, value: Any) -> Optional[str]:
    """Return error string or None if valid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if spec.required:
            return "required"
        return None

    sv = str(value).strip()

    if spec.field_type == "enum" and spec.allowed_values:
        if sv.lower() not in [av.lower() for av in spec.allowed_values]:
            return f"must be one of: {', '.join(spec.allowed_values)}"

    elif spec.field_type == "date":
        try:
            datetime.strptime(sv, "%Y-%m-%d")
        except ValueError:
            return "must be a valid date (YYYY-MM-DD)"

    elif spec.field_type == "number":
        try:
            float(sv)
        except ValueError:
            return "must be a number"

    elif spec.field_type == "regex" and spec.validation_regex:
        if not re.fullmatch(spec.validation_regex, sv):
            return f"does not match required format ({spec.validation_regex})"

    return None


# ─── FSM step logic ───────────────────────────────────────────────────────────

@dataclass
class FSMResult:
    """Result of advancing the FSM one step."""
    state: str              # COLLECT | VALIDATE_ERROR | GATE | DONE | ROUTE
    missing_fields: List[str] = field(default_factory=list)
    validation_errors: Dict[str, str] = field(default_factory=dict)
    next_step: Optional[StepDef] = None
    prompt_fields: List[str] = field(default_factory=list)  # 1-2 fields to ask for
    route_reason: Optional[str] = None
    route_team: Optional[str] = None
    summary: Optional[str] = None


def advance_fsm(
    wf: WorkflowDef,
    slots: Dict[str, Any],
    vault_keys: set,            # Set of field names in vault (sensitive)
    thresholds: Dict[str, float],
) -> FSMResult:
    """
    Advance the FSM given current slots.
    Returns the next action for the pipeline.
    """
    all_collected = set(slots.keys()) | vault_keys

    # Validate what we have
    validation = validate_slots(wf, slots)
    if not validation.ok:
        return FSMResult(
            state="VALIDATE_ERROR",
            validation_errors=validation.errors,
        )

    current_step = wf.current_step(all_collected)
    if current_step is None:
        # All steps done → GATE check
        return FSMResult(state="GATE", summary=_build_summary(wf, slots))

    # Find missing fields for current step, ask 1-2 at a time
    missing = [f for f in current_step.fields if f.required and f.name not in all_collected]
    prompt_fields = [f.name for f in missing[:2]]

    return FSMResult(
        state="COLLECT",
        missing_fields=[f.name for f in missing],
        prompt_fields=prompt_fields,
        next_step=current_step,
    )


def _build_summary(wf: WorkflowDef, slots: Dict[str, Any]) -> str:
    lines = [f"Workflow: {wf.title}"]
    for k, v in slots.items():
        lines.append(f"  {k}: {v}")
    if wf.governing_article_id:
        lines.append(f"  Governing article: {wf.governing_article_id}")
    return "\n".join(lines)
