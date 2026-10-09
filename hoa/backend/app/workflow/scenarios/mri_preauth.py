"""
MRI Pre-Authorization workflow handler.

Handles the full MRI pre-auth scenario:
- Collect: insurer, procedure_code, scheduled_date, authorization_status, patient_mrn
- Insurer requires auth (per KB) → show form + system + pending steps
- Authorization status: pending → show steps; rejected → ROUTE to TPA/Insurance team
- Unknown insurer → ask clarifying question once, then ROUTE

Returns WorkflowAction to the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# ─── Insurers that require pre-authorization (from knowledge base policy) ─────
# Source: ART-007 Pre-Authorization Requirements Policy
_INSURERS_REQUIRING_AUTH: frozenset[str] = frozenset({
    "bcbs", "blue cross", "blue shield", "aetna", "cigna", "united", "unitedhealthcare",
    "humana", "kaiser", "anthem", "medicare", "medicaid", "tpa",
})

_KNOWN_INSURERS: frozenset[str] = frozenset(
    _INSURERS_REQUIRING_AUTH | {"self-pay", "self pay", "cash pay", "tricare", "champva"}
)


@dataclass
class WorkflowAction:
    """Action returned by scenario handlers."""
    state: str           # COLLECT | GUIDE | ROUTE | DONE
    text: str
    prompt_fields: List[str] = field(default_factory=list)
    route_team: Optional[str] = None
    route_reason: Optional[str] = None
    summary: Optional[str] = None
    citations: List[str] = field(default_factory=list)
    form: Optional[str] = None
    system: Optional[str] = None


# ─── MRI Pre-Authorization scenario ─────────────────────────────────────────

MRI_REQUIRED_FIELDS = ["insurer", "procedure_code", "scheduled_date", "authorization_status", "patient_mrn"]
MRI_SENSITIVE_FIELDS = {"patient_mrn"}


def handle_mri_preauth(
    slots: Dict[str, Any],
    vault_keys: set,
    governing_article_id: Optional[str],
) -> WorkflowAction:
    """
    Drive the MRI pre-authorization scenario through its FSM.
    slots: non-sensitive collected slots
    vault_keys: set of field names in the encrypted vault
    """
    all_collected = set(slots.keys()) | vault_keys

    # ── Step 1: Collect insurer ──────────────────────────────────────────────
    if "insurer" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="To begin MRI pre-authorization, I need some details. What is the patient's insurance provider?",
            prompt_fields=["insurer"],
        )

    insurer = str(slots.get("insurer", "")).strip().lower()

    # ── Unknown insurer path ─────────────────────────────────────────────────
    if insurer and insurer not in _KNOWN_INSURERS and not any(k in insurer for k in _KNOWN_INSURERS):
        if slots.get("_insurer_clarified"):
            # Already asked once → ROUTE
            return WorkflowAction(
                state="ROUTE",
                text=(
                    f"The insurer '{slots.get('insurer')}' is not in our system. "
                    f"Routing to the Insurance/TPA team for manual verification."
                ),
                route_team="Insurance/TPA",
                route_reason="unknown_insurer",
                citations=[governing_article_id] if governing_article_id else [],
            )
        return WorkflowAction(
            state="COLLECT",
            text=(
                f"I don't recognize '{slots.get('insurer')}' as a known insurer. "
                "Could you double-check the insurer name or provide the policy/group number?"
            ),
            prompt_fields=["insurer"],
        )

    # ── Step 2: Procedure code ──────────────────────────────────────────────
    if "procedure_code" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="What is the CPT/procedure code for the MRI? (e.g., 70553 for MRI Brain with contrast)",
            prompt_fields=["procedure_code"],
        )

    # ── Step 3: Scheduled date ──────────────────────────────────────────────
    if "scheduled_date" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="What is the scheduled date for the MRI? (YYYY-MM-DD)",
            prompt_fields=["scheduled_date"],
        )

    # ── Step 4: Patient MRN (sensitive — goes to vault) ────────────────────
    if "patient_mrn" not in vault_keys:
        return WorkflowAction(
            state="COLLECT",
            text="Please provide the patient's Medical Record Number (MRN).",
            prompt_fields=["patient_mrn"],
        )

    # ── Step 5: Check if insurer requires auth ──────────────────────────────
    requires_auth = _insurer_requires_auth(insurer)
    if not requires_auth:
        # Self-pay or exempt insurer → no auth needed
        return WorkflowAction(
            state="DONE",
            text=(
                f"Good news: **{slots.get('insurer')}** does not require MRI pre-authorization. "
                "You may proceed with scheduling. Document the procedure in PACS and EMR."
            ),
            form="MRI-PreAuth-Form",
            system="PACS",
            citations=[governing_article_id] if governing_article_id else [],
        )

    # ── Step 6: Authorization status ────────────────────────────────────────
    if "authorization_status" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text=(
                f"**{slots.get('insurer')}** requires MRI pre-authorization per policy. "
                "[ART-007]\n\n"
                "Please submit the pre-authorization request via the **MRI-PreAuth-Form** "
                "in **PACS**. What is the current authorization status? "
                "(approved / pending / rejected / not_submitted)"
            ),
            prompt_fields=["authorization_status"],
            form="MRI-PreAuth-Form",
            system="PACS",
            citations=[governing_article_id] if governing_article_id else [],
        )

    auth_status = str(slots.get("authorization_status", "")).strip().lower()

    # ── Approved ─────────────────────────────────────────────────────────────
    if auth_status in ("approved", "authorized"):
        return WorkflowAction(
            state="DONE",
            text=(
                "✅ **Authorization approved.** Next steps:\n"
                "1. Record the authorization number in PACS and EMR.\n"
                "2. Notify the Radiology team and patient with the appointment date.\n"
                "3. Complete the **MRI-PreAuth-Form** and file in the patient record.\n\n"
                f"Governing policy: ART-007."
            ),
            form="MRI-PreAuth-Form",
            system="PACS",
            citations=[governing_article_id] if governing_article_id else [],
        )

    # ── Pending ──────────────────────────────────────────────────────────────
    if auth_status == "pending":
        return WorkflowAction(
            state="GUIDE",
            text=(
                "⏳ **Authorization is pending.** While awaiting the insurer's decision:\n"
                "1. Check the payer portal daily for status updates.\n"
                "2. Contact the **Insurance/TPA** team if no response within 2 business days.\n"
                "3. Do **not** schedule the MRI until authorization is confirmed.\n\n"
                f"Governing policy: ART-007."
            ),
            form="MRI-PreAuth-Form",
            system="PACS",
            citations=[governing_article_id] if governing_article_id else [],
        )

    # ── Rejected ─────────────────────────────────────────────────────────────
    if auth_status in ("rejected", "denied"):
        insurer_name = slots.get("insurer", "the insurer")
        proc_code = slots.get("procedure_code", "")
        return WorkflowAction(
            state="ROUTE",
            text=(
                f"❌ **Authorization rejected by {insurer_name}**.\n\n"
                "This request is being routed to the **Insurance/TPA** team with a pre-filled summary.\n"
                "They will initiate the appeal process per ART-007.\n\n"
                "**Pre-filled summary:**\n"
                f"- Insurer: {insurer_name}\n"
                f"- Procedure: {proc_code}\n"
                f"- Scheduled date: {slots.get('scheduled_date', 'TBD')}\n"
                f"- Authorization status: Rejected\n"
                f"- Governing policy: ART-007"
            ),
            route_team="Insurance/TPA",
            route_reason="authorization_rejected",
            summary=(
                f"MRI pre-auth rejected for procedure {proc_code} by {insurer_name}. "
                f"Scheduled: {slots.get('scheduled_date', 'TBD')}. Requires appeal."
            ),
            citations=[governing_article_id] if governing_article_id else [],
            form="MRI-PreAuth-Form",
            system="PACS",
        )

    # ── Not submitted yet ─────────────────────────────────────────────────────
    return WorkflowAction(
        state="GUIDE",
        text=(
            f"**{slots.get('insurer')}** requires pre-authorization for MRI procedures. [ART-007]\n\n"
            "**Action required:**\n"
            "1. Complete the **MRI-PreAuth-Form** in **PACS**.\n"
            "2. Submit the pre-authorization request to the payer portal.\n"
            "3. Update the authorization status once you receive a response.\n\n"
            "What is the current authorization status? (approved / pending / rejected)"
        ),
        prompt_fields=["authorization_status"],
        form="MRI-PreAuth-Form",
        system="PACS",
        citations=[governing_article_id] if governing_article_id else [],
    )


def _insurer_requires_auth(insurer_lower: str) -> bool:
    """Check if the insurer requires pre-authorization based on the knowledge base."""
    return any(k in insurer_lower for k in _INSURERS_REQUIRING_AUTH)
