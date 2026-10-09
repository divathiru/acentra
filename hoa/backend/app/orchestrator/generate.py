"""
Generate module — template-first answer builder with citation guard.
"""
from __future__ import annotations

import re
import structlog
from typing import List, Optional

from app.knowledge.api import EvidenceBundle
from app.llm.api import LLMPort, ModelTier
from app.llm.understand import QueryIntent

logger = structlog.get_logger(__name__)


# ─── Citation helpers ─────────────────────────────────────────────────────────

def _citation_tag(node_id: str, nodes: dict) -> str:
    """Build a [ART-###] or [NODE-id] citation string."""
    node = nodes.get(node_id, {})
    title = node.get("title", node_id)
    return f"[{title[:40]}]"


def _build_template_answer(bundle: EvidenceBundle) -> str:
    """
    Build a factual template answer directly from evidence node fields.
    Every sentence contains a citation.
    """
    if not bundle.nodes:
        return "No relevant approved documents were found for your query."

    lines = []
    for nid in bundle.entry_nodes:
        node = bundle.nodes.get(nid)
        if not node:
            continue
        citation = f"[{nid}]"
        title = node.get("title", "Policy")
        body = node.get("body", "").strip()

        # Superseded note
        if nid in bundle.superseded_notes:
            lines.append(f"⚠️ Note: A newer version exists for this article. {bundle.superseded_notes[nid]} {citation}")

        if body:
            # Strip any brackets from the body to avoid false citation guard failures
            clean_body = re.sub(r'\[[^\]]*\]', '', body).strip()
            # Take first 3 sentences with citation
            sentences = re.split(r'(?<=[.!?])\s+', clean_body)
            added = 0
            for sent in sentences:
                sent = sent.strip()
                if sent and added < 3:
                    lines.append(f"{sent} {citation}")
                    added += 1
            if added == 0:
                lines.append(f"Per {title}: see policy for details. {citation}")
        else:
            lines.append(f"Per {title}: No detailed body available. {citation}")

    # Attach related step/form/team info from edges
    step_nodes = [
        bundle.nodes[e["to_id"]]
        for e in bundle.edges
        if e["type"] == "has_step" and e["to_id"] in bundle.nodes
    ]
    if step_nodes:
        steps_text = "; ".join(
            f"Step {i+1}: {n.get('title', '')}" for i, n in enumerate(step_nodes[:5])
        )
        first_wf = next(
            (e["from_id"] for e in bundle.edges if e["type"] == "has_step"),
            list(bundle.entry_nodes)[0] if bundle.entry_nodes else "unknown"
        )
        lines.append(f"Workflow steps: {steps_text}. [{first_wf}]")

    return "\n".join(lines) if lines else "No structured answer could be built from available sources."



def _citation_guard(text: str, bundle: EvidenceBundle) -> bool:
    """
    Verify the generated response:
    - Every bracketed reference [xxx] must be in the bundle.
    - Content paragraphs (> 8 words, not a heading) must have at least one citation.
    """
    refs = re.findall(r'\[([^\]]+)\]', text)
    all_node_ids = set(bundle.nodes.keys())
    all_node_titles = {v.get("title", "") for v in bundle.nodes.values()}

    for ref in refs:
        if ref not in all_node_ids and ref not in all_node_titles:
            logger.warning("Citation guard: unknown reference", ref=ref)
            return False

    paragraphs = [p for p in text.split("\n") if p.strip()]
    for para in paragraphs:
        word_count = len(para.split())
        # Skip short headers/titles (< 8 words) and warning banners starting with ⚠️
        if word_count < 8 or para.startswith("⚠️"):
            continue
        if not re.search(r'\[', para):
            logger.warning("Citation guard: content paragraph without citation", para=para[:80])
            return False

    return True


# ─── Main generate function ───────────────────────────────────────────────────

async def generate(
    query: str,
    bundle: EvidenceBundle,
    verification: dict,
    intent: QueryIntent,
    llm: LLMPort,
    is_medium_band: bool = False,
) -> tuple[str, str]:
    """
    Returns (answer_text, mode).
    Template-first: build from evidence, then optionally rephrase with LLM.
    If citation guard fails on LLM output, fall back to pure template.
    If template also fails citation guard, ROUTE is signalled via exception.
    """
    template_answer = _build_template_answer(bundle)

    # Medium-band: append uncertainty notice
    if is_medium_band:
        template_answer += (
            "\n\n⚠️ Some information may be incomplete. "
            "Would you like me to route this to the appropriate team for a definitive answer?"
        )

    # Try LLM rephrasing
    evidence_context = "\n\n".join(
        f"<untrusted_hospital_record id='{nid}'>\n{node.get('body','')}\n</untrusted_hospital_record>"
        for nid, node in bundle.nodes.items()
        if nid in bundle.entry_nodes
    )

    system_prompt = (
        "You are a hospital operations assistant. Rephrase the following verified answer into "
        "friendly, concise prose. Keep ALL citation brackets exactly as-is. "
        "Never add information not present in the evidence. "
        "Every sentence must include at least one citation bracket.\n\n"
        f"Evidence:\n{evidence_context}"
    )

    try:
        resp = await llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Rephrase this answer:\n{template_answer}"},
            ],
            tier=ModelTier.PRIMARY,
            json_mode=False,
            timeout=10.0,
        )
        llm_text = resp.text

        if _citation_guard(llm_text, bundle):
            return llm_text, resp.mode
        else:
            logger.warning("Citation guard failed on LLM output — falling back to template")
    except Exception as e:
        logger.warning("LLM generate failed", error=str(e))

    # Template fallback
    if _citation_guard(template_answer, bundle):
        return template_answer, "template"

    # Both failed — signal to pipeline to ROUTE
    raise ValueError("Citation guard failed on template answer — routing required")
