"""
Hyperparameter tuning module for Verify weights and decision thresholds.
Performs grid-search ON THE SEED SPLIT ONLY.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Any, List
import structlog
from sqlalchemy.orm import Session

from app.core.models import EvalCase, PolicyThreshold, User
from app.llm.api import get_llm
from app.orchestrator.pipeline import run_pipeline
from app.knowledge.api import RetrieveFlags

logger = structlog.get_logger(__name__)

TUNED_CONFIG_PATH = "data/tuned_verify_config.json"


async def grid_search_tuning(db: Session) -> Dict[str, Any]:
    """
    Grid-search optimal Verify weights and confidence thresholds on SEED split only.
    Saves chosen values to config JSON and updates DB policy thresholds.
    """
    seed_cases = db.query(EvalCase).filter(EvalCase.split == "seed").all()
    if not seed_cases:
        logger.warning("grid_search.no_seed_cases")
        return {}

    seed_cases = seed_cases[:20]
    logger.info("grid_search.started", num_seed_cases=len(seed_cases))

    # Grid search candidate parameters
    grid = [
        {"verify_weight_sim": 0.40, "verify_weight_cov": 0.40, "verify_weight_ent": 0.20, "verify_band_high": 0.70, "verify_band_medium": 0.45},
        {"verify_weight_sim": 0.50, "verify_weight_cov": 0.35, "verify_weight_ent": 0.15, "verify_band_high": 0.65, "verify_band_medium": 0.40},
        {"verify_weight_sim": 0.35, "verify_weight_cov": 0.45, "verify_weight_ent": 0.20, "verify_band_high": 0.75, "verify_band_medium": 0.50},
    ]

    user = db.query(User).first()
    user_id = str(user.id) if user else "00000000-0000-0000-0000-000000000000"

    llm = get_llm(db)
    flags = RetrieveFlags(use_fts=True, use_graph=True)

    best_score = -1.0
    best_candidate = grid[0]

    for candidate in grid:
        correct_count = 0
        total = 0

        for case in seed_cases:
            query = case.input_json.get("query", "")
            expected = case.expected_json
            expected_outcome = expected.get("outcome")

            try:
                resp, _ = await run_pipeline(
                    query=query,
                    user_id=user_id,
                    dept_role="ALL",
                    session=db,
                    llm=llm,
                    retrieve_flags=flags,
                    override_config=candidate,
                )
                actual_outcome = getattr(resp, "outcome", "")

                if actual_outcome == expected_outcome:
                    correct_count += 1
                total += 1
            except Exception as e:
                db.rollback()
                logger.error("grid_search.error", case_id=case.id, error=str(e))

        acc = (correct_count / total) if total > 0 else 0.0
        logger.info("grid_search.candidate_evaluated", candidate=candidate, accuracy=acc)

        if acc > best_score:
            best_score = acc
            best_candidate = candidate

    logger.info("grid_search.completed", best_candidate=best_candidate, best_score=best_score)

    # Persist best candidate config
    os.makedirs(os.path.dirname(TUNED_CONFIG_PATH), exist_ok=True)
    with open(TUNED_CONFIG_PATH, "w") as f:
        json.dump(best_candidate, f, indent=2)

    # Update policy thresholds in DB
    for key, val in best_candidate.items():
        threshold = db.query(PolicyThreshold).filter(PolicyThreshold.key == key).first()
        if threshold:
            threshold.value = float(val)
        else:
            db.add(PolicyThreshold(key=key, value=float(val), description=f"Tuned parameter {key}"))
    db.commit()

    return best_candidate
