"""
Unit tests for Task 11: Evaluation harness and proof of value.
Tests seeding, ablation runner, Wilson CI, and DB persistence.
"""

from __future__ import annotations

import os
import uuid
import pytest

from app.core.database import SessionLocal
from app.eval.cases import seed_eval_cases
from app.eval.runner import run_full_eval_suite
from app.eval.wilson import wilson_score_interval, format_wilson
from app.core.models import EvalCase, EvalRun, EvalResult


# ---------------------------------------------------------------------------
# Wilson CI unit tests (pure, no DB)
# ---------------------------------------------------------------------------

def test_wilson_perfect():
    rate, lo, hi = wilson_score_interval(10, 10)
    assert rate == pytest.approx(100.0, abs=0.1)
    assert lo >= 69.0  # well above zero even at perfect recall


def test_wilson_zero():
    rate, lo, hi = wilson_score_interval(0, 10)
    assert rate == pytest.approx(0.0, abs=0.1)
    assert hi <= 31.0


def test_wilson_half():
    rate, lo, hi = wilson_score_interval(5, 10)
    # midpoint around 50%, CI must straddle it
    assert lo < 50.0
    assert hi > 50.0


def test_wilson_zero_denom():
    rate, lo, hi = wilson_score_interval(0, 0)
    assert rate == 0.0
    assert lo == 0.0
    assert hi == 0.0


def test_format_wilson_string():
    s = format_wilson(8, 10)
    assert "%" in s
    assert "95%" not in s or "n=10" in s  # format includes n=
    assert "80.0%" in s  # 8/10 = 80%


def test_format_wilson_zero_denom():
    s = format_wilson(0, 0)
    assert "n=0" in s


# ---------------------------------------------------------------------------
# Eval case seeding
# ---------------------------------------------------------------------------

def test_eval_cases_seeded():
    with SessionLocal() as db:
        # Seed (idempotent)
        seed_eval_cases(db)
        count = db.query(EvalCase).count()
        assert count >= 2, "Should have at least FALLBACK_CASES seeded"

        # Check splits exist
        seed_c = db.query(EvalCase).filter(EvalCase.split == "seed").count()
        held_c = db.query(EvalCase).filter(EvalCase.split == "heldout").count()
        assert seed_c >= 1
        assert held_c >= 1


# ---------------------------------------------------------------------------
# Full evaluation suite (template LLM, no Mistral calls)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eval_suite_execution():
    """Test seeding eval cases, running eval suite, and verifying metrics."""
    os.environ["LLM_PROVIDER"] = "template"
    os.environ["MISTRAL_API_KEY"] = ""

    with SessionLocal() as db:
        seed_eval_cases(db)
        cases = db.query(EvalCase).all()
        assert len(cases) >= 2

        # Run ablation on seed split (smaller, faster)
        summary = await run_full_eval_suite(db, split="seed")

        assert summary["status"] == "completed"
        assert "ablation_summary" in summary
        ablation = summary["ablation_summary"]

        # Must return all 3 configs
        assert len(ablation) == 3
        names = [c["config_name"] for c in ablation]
        assert any("Vector-Only" in n for n in names)
        assert any("Hybrid" in n and "Graph" not in n for n in names)
        assert any("Graph" in n for n in names)

        # Each config has required metric keys
        for config_result in ablation:
            assert "routing_accuracy" in config_result
            assert "outcome_accuracy" in config_result
            assert "citation_validity" in config_result
            assert "safety_pass_rate" in config_result
            assert "latency_deterministic_p50_ms" in config_result
            assert "latency_llm_p50_ms" in config_result
            assert "n" in config_result

        # DB persistence: EvalRun should have been created
        run_id = uuid.UUID(summary["run_id"])
        run_record = db.query(EvalRun).filter(EvalRun.id == run_id).first()
        assert run_record is not None

        # EvalResult records should exist for the run
        result_records = db.query(EvalResult).filter(
            EvalResult.run_id == run_record.id
        ).all()
        assert len(result_records) >= 2
