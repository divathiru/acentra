"""
Specimen Rejection and Resubmission workflow scenario.

Steps:
1. Identify rejection reason and specimen ID
2. Notify requesting physician
3. Collect new specimen with new_collection_datetime
4. Label/document chain of custody
5. Resubmit to lab
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

SPECIMEN_REQUIRED_FIELDS = ["specimen_id", "rejection_reason", "requesting_physician", "new_collection_datetime"]

REJECTION_REASONS = [
    "hemolysis", "clotting", "insufficient_volume", "wrong_tube",
    "labeling_error", "transport_delay", "contamination", "other",
]


def handle_specimen_rejection(
    slots: Dict[str, Any],
    vault_keys: set,
    governing_article_id: Optional[str],
) -> "WorkflowAction":
    from app.workflow.scenarios.mri_preauth import WorkflowAction

    all_collected = set(slots.keys()) | vault_keys

    # ── Step 1: Specimen ID ──────────────────────────────────────────────────
    if "specimen_id" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="To process specimen rejection, what is the specimen ID / accession number?",
            prompt_fields=["specimen_id"],
        )

    # ── Step 2: Rejection reason ─────────────────────────────────────────────
    if "rejection_reason" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text=(
                f"What is the reason for rejecting specimen **{slots.get('specimen_id')}**?\n"
                f"Options: {', '.join(REJECTION_REASONS)}"
            ),
            prompt_fields=["rejection_reason"],
        )

    # ── Step 3: Requesting physician ─────────────────────────────────────────
    if "requesting_physician" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text="Who is the requesting physician to be notified of the rejection?",
            prompt_fields=["requesting_physician"],
        )

    # ── Step 4: New collection datetime ─────────────────────────────────────
    if "new_collection_datetime" not in all_collected:
        return WorkflowAction(
            state="COLLECT",
            text=(
                f"Dr. **{slots.get('requesting_physician')}** has been notified of the rejection "
                f"(reason: {slots.get('rejection_reason')}).\n\n"
                "Please schedule a re-collection. What is the new collection date and time? (YYYY-MM-DD HH:MM)"
            ),
            prompt_fields=["new_collection_datetime"],
        )

    # ── All collected → GUIDE through resubmission ───────────────────────────
    reason = slots.get("rejection_reason", "")
    spec_id = slots.get("specimen_id", "")
    physician = slots.get("requesting_physician", "")
    new_dt = slots.get("new_collection_datetime", "")

    return WorkflowAction(
        state="GUIDE",
        text=(
            f"✅ **Specimen resubmission initiated for {spec_id}.**\n\n"
            "**Action checklist:**\n"
            f"1. Physician **{physician}** notified — rejection reason: *{reason}*.\n"
            f"2. Re-collection scheduled: **{new_dt}**.\n"
            "3. Label the new specimen tube with:\n"
            "   - Patient name and MRN\n"
            "   - Collection date/time\n"
            "   - Collector initials\n"
            "4. Document chain of custody in the LIS.\n"
            "5. Transport to lab within the specimen-type time window.\n"
            "6. Resubmit the lab order — select **Resubmit** in the LIS.\n\n"
            "⚠️ Ensure all labeling corrections are documented per chain-of-custody protocol."
        ),
        citations=[governing_article_id] if governing_article_id else [],
    )
