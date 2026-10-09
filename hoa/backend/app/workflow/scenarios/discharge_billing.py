"""
Discharge Billing Clearance workflow scenario.

Steps:
1. Collect outstanding charges, patient balance, insurance coverage, discharge date
2. If total_charges > billing_supervisor_approval_threshold → ROUTE to Billing Supervisor
3. Else GUIDE through clearance steps
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

DISCHARGE_REQUIRED_FIELDS = [
    "discharge_date", "total_charges", "insurance_coverage_amount", "patient_balance"
]

DISCHARGE_SENSITIVE_FIELDS: frozenset[str] = frozenset()  # no PHI in billing clearance


def handle_discharge_billing(
    slots: Dict[str, Any],
    vault_keys: set,
    thresholds: Dict[str, float],
    governing_article_id: Optional[str],
) -> "WorkflowAction":
    from app.workflow.scenarios.mri_preauth import WorkflowAction

    all_collected = set(slots.keys()) | vault_keys

    # ── Step 1: Discharge date ───────────────────────────────────────────────
    if "discharge_date" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="To process discharge billing clearance, I need the discharge date (YYYY-MM-DD).",
            prompt_fields=["discharge_date"],
        )

    # ── Step 2: Total charges ────────────────────────────────────────────────
    if "total_charges" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="What are the total charges for this patient's stay? (numeric value in USD)",
            prompt_fields=["total_charges"],
        )

    # ── Step 3: Insurance coverage amount ────────────────────────────────────
    if "insurance_coverage_amount" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="What is the insurance coverage amount for this encounter? (numeric value in USD, or 0 if self-pay)",
            prompt_fields=["insurance_coverage_amount"],
        )

    # ── Step 4: Patient balance ──────────────────────────────────────────────
    if "patient_balance" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="What is the remaining patient balance after insurance? (numeric value in USD)",
            prompt_fields=["patient_balance"],
        )

    # ── Gate: check approval threshold ──────────────────────────────────────
    approval_threshold = float(thresholds.get("billing_supervisor_approval_threshold", 5000.0))
    try:
        total = float(slots.get("total_charges", 0))
        balance = float(slots.get("patient_balance", 0))
    except (TypeError, ValueError):
        total = 0.0
        balance = 0.0

    if total > approval_threshold or balance > approval_threshold:
        return WorkflowAction(
            state="ROUTE",
            text=(
                f"⚠️ **Billing Supervisor approval required.**\n\n"
                f"Total charges of **${total:,.2f}** exceed the approval threshold of **${approval_threshold:,.2f}**.\n\n"
                f"This discharge billing clearance has been routed to the **Billing Supervisor** for review.\n\n"
                f"**Summary:**\n"
                f"- Discharge date: {slots.get('discharge_date')}\n"
                f"- Total charges: ${total:,.2f}\n"
                f"- Insurance coverage: ${float(slots.get('insurance_coverage_amount', 0)):,.2f}\n"
                f"- Patient balance: ${balance:,.2f}\n"
            ),
            route_team="Billing Supervisor",
            route_reason="amount_above_threshold",
            summary=(
                f"Discharge billing clearance requires Billing Supervisor approval. "
                f"Total: ${total:,.2f} > threshold ${approval_threshold:,.2f}. "
                f"Discharge date: {slots.get('discharge_date')}."
            ),
            citations=[governing_article_id] if governing_article_id else [],
        )

    # Within threshold — GUIDE through clearance steps
    return WorkflowAction(
        state="GUIDE",
        text=(
            f"✅ **Billing clearance approved.** Total charges: **${total:,.2f}**.\n\n"
            "**Next steps:**\n"
            "1. Verify insurance coverage in the billing system.\n"
            "2. Generate the final patient statement.\n"
            "3. Submit the final claim to the insurance provider.\n"
            "4. Record clearance in the EMR and flag for accounts receivable.\n\n"
            f"Patient balance due: **${balance:,.2f}**."
        ),
        citations=[governing_article_id] if governing_article_id else [],
    )
