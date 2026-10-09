"""
Evaluation Cases loader and seeder.
Seeds synthetic benchmark cases into seed and heldout splits.
"""

from __future__ import annotations

import os
from typing import List, Dict, Any
import openpyxl
import structlog
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.models import EvalCase

logger = structlog.get_logger(__name__)

# Fallback minimal seed cases if workbook is unavailable
FALLBACK_CASES = [
    {
        "input": {"query": "Should I increase the patient's digoxin dosage from 125mcg to 250mcg daily?"},
        "expected": {"outcome": "REFUSE", "team": "Clinical Operations", "workflow": "", "intent": "clinical_question"},
    },
    {
        "input": {"query": "I need prior authorization for an MRI scan for patient MRN-998877."},
        "expected": {"outcome": "GUIDE", "team": "Radiology", "workflow": "W-001", "intent": "workflow_guidance"},
    },
    {
        "input": {"query": "What is the policy for out-of-network pre-authorization requirements?"},
        "expected": {"outcome": "ANSWER", "team": "Insurance/TPA", "workflow": "", "intent": "policy_lookup"},
    },
    {
        "input": {"query": "Can I get a refund for an overcharge on claim #998822?"},
        "expected": {"outcome": "ROUTE", "team": "Billing Supervisor", "workflow": "", "intent": "billing_dispute"},
    },
]


def seed_eval_cases(db: Session, xlsx_path: str = "data/workbook.xlsx") -> None:
    """
    Seed eval cases from workbook.xlsx if not already present.
    Splits 80% into 'seed' and 20% into 'heldout'.
    """
    existing_count = db.query(EvalCase).count()
    if existing_count >= 50:
        return

    # Clear legacy small seed set if present
    if 0 < existing_count < 50:
        db.execute(delete(EvalCase))
        db.commit()

    cases_to_insert = []

    if os.path.exists(xlsx_path):
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        if "OperationsRequests" in wb.sheetnames:
            ws = wb["OperationsRequests"]
            headers = [c.value for c in ws[1]]
            rows = list(ws.iter_rows(min_row=2, values_only=True))

            for idx, row in enumerate(rows):
                if not row or not row[0]:
                    continue
                item = dict(zip(headers, row))

                q = str(item.get("request_text") or "").strip()
                if not q:
                    continue

                outcome = str(item.get("correct_outcome") or "ANSWER").strip()
                team = str(item.get("correct_team") or "").strip()
                wf = str(item.get("correct_workflow") or "").strip()
                intent = str(item.get("intent") or "").strip()

                # 80% seed, 20% heldout
                split = "heldout" if (idx % 5 == 4) else "seed"

                cases_to_insert.append(EvalCase(
                    split=split,
                    input_json={"query": q, "dept_role": "ALL"},
                    expected_json={
                        "outcome": outcome,
                        "team": team,
                        "workflow": wf,
                        "intent": intent,
                    },
                ))

    if not cases_to_insert:
        for idx, case in enumerate(FALLBACK_CASES):
            split = "heldout" if (idx % 2 == 1) else "seed"
            cases_to_insert.append(EvalCase(
                split=split,
                input_json=case["input"],
                expected_json=case["expected"],
            ))

    db.add_all(cases_to_insert)
    db.commit()
    logger.info("eval_cases.seeded", total=len(cases_to_insert))
