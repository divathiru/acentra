"""
CLI entrypoint for running evaluation suite and generating Markdown ablation table.
Executed by `make eval` and CI/CD nightly workflow.
"""

import asyncio
import sys
import structlog

from app.core.database import SessionLocal
from app.eval.cases import seed_eval_cases
from app.eval.tuning import grid_search_tuning
from app.eval.runner import run_full_eval_suite

logger = structlog.get_logger(__name__)


def print_markdown_ablation(summary: dict) -> float:
    """Prints formatted Markdown ablation table to stdout. Returns Config C routing accuracy pct."""
    ablation = summary.get("ablation_summary", [])

    print("\n# HOA Evaluation & Proof of Value Ablation Report")
    print(f"**Split:** {summary.get('split', 'heldout')} | **Timestamp:** {summary.get('timestamp')}\n")

    headers = [
        "Configuration",
        "Routing Acc (95% CI)",
        "Outcome Acc (95% CI)",
        "Citation Validity",
        "5-Q Coverage",
        "Unsupported Rate",
        "Safety Pass",
        "Det p50/p95 (ms)",
        "LLM p50/p95 (ms)",
    ]

    header_row = "| " + " | ".join(headers) + " |"
    divider_row = "| " + " | ".join(["---"] * len(headers)) + " |"

    print(header_row)
    print(divider_row)

    config_c_routing_pct = 0.0

    for item in ablation:
        name = item.get("config_name", "")
        rout = item.get("routing_accuracy", "")
        out = item.get("outcome_accuracy", "")
        cit = item.get("citation_validity", "")
        five_q = item.get("five_question_coverage", "")
        unsupp = item.get("unsupported_answer_rate", "")
        safe = item.get("safety_pass_rate", "")
        det = f"{item.get('latency_deterministic_p50_ms', 0)} / {item.get('latency_deterministic_p95_ms', 0)}"
        llm = f"{item.get('latency_llm_p50_ms', 0)} / {item.get('latency_llm_p95_ms', 0)}"

        if "Config C" in name:
            config_c_routing_pct = item.get("routing_accuracy_pct", 0.0)

        row = f"| {name} | {rout} | {out} | {cit} | {five_q} | {unsupp} | {safe} | {det} | {llm} |"
        print(row)

    print("\n")
    return config_c_routing_pct


async def main():
    print("Initializing evaluation database session...")
    with SessionLocal() as db:
        # Step 1: Seed benchmark cases
        seed_eval_cases(db)

        # Step 2: Grid-search tuning on SEED split only
        print("Running grid-search tuning on SEED split...")
        await grid_search_tuning(db)

        # Step 3: Run evaluation harness on HELDOUT split
        print("Running evaluation suite on HELDOUT split...")
        summary = await run_full_eval_suite(db, split="heldout")

    # Step 4: Print Markdown table
    config_c_routing_pct = print_markdown_ablation(summary)

    # Check exit criterion (nightly job fails if routing accuracy < 90%)
    if "--strict" in sys.argv and config_c_routing_pct < 90.0:
        print(f"FAILED: Config C routing accuracy ({config_c_routing_pct:.1f}%) is below 90% threshold.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"SUCCESS: Config C routing accuracy is {config_c_routing_pct:.1f}%.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
