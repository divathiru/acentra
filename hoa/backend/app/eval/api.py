"""
Evaluation and Benchmarking API endpoints.
Provides GET /eval/results and POST /eval/run.
"""

from __future__ import annotations

import os
import json
from typing import Dict, Any
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.eval.cases import seed_eval_cases
from app.eval.runner import run_full_eval_suite, EVAL_OUTPUT_PATH
from app.eval.tuning import grid_search_tuning

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/results")
async def get_eval_results(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get the latest evaluation results, 3-row ablation table with Wilson 95% CIs, and latency splits.
    """
    if os.path.exists(EVAL_OUTPUT_PATH):
        try:
            with open(EVAL_OUTPUT_PATH, "r") as f:
                data = json.load(f)
                return data
        except Exception as e:
            logger.error("eval.read_results_error", error=str(e))

    # If no file exists, run a quick evaluation suite
    seed_eval_cases(db)
    results = await run_full_eval_suite(db, split="heldout")
    return results


@router.post("/run")
async def trigger_eval_run(
    split: str = "heldout",
    tune: bool = False,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trigger a fresh evaluation run across Configs A, B, and C.
    Optionally performs grid-search tuning on SEED split first.
    """
    seed_eval_cases(db)
    if tune:
        await grid_search_tuning(db)

    results = await run_full_eval_suite(db, split=split)
    return results
