"""Intent understanding step — deterministic fallback → Pydantic → LLM."""

from __future__ import annotations

import json
import re
import structlog
from pathlib import Path
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, ValidationError, field_validator

logger = structlog.get_logger(__name__)

PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "understand.md"

# ─── Schema ───────────────────────────────────────────────────────────────────

class QueryEntities(BaseModel):
    insurer: Optional[str] = None
    procedure: Optional[str] = None
    department: Optional[str] = None
    system: Optional[str] = None

class QueryIntent(BaseModel):
    kind: str
    workflow_id: Optional[str] = None
    entities: QueryEntities = QueryEntities()
    urgency: str = "normal"
    sentiment: str = "neutral"
    issue_type: str = ""

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        valid = {
            "knowledge_question", "start_workflow", "workflow_reply",
            "status_check", "complaint", "sensitive_report", "unclear"
        }
        return v if v in valid else "unclear"

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: str) -> str:
        return v if v in {"low", "normal", "high"} else "normal"

    @field_validator("sentiment")
    @classmethod
    def validate_sentiment(cls, v: str) -> str:
        return v if v in {"neg", "neutral", "pos"} else "neutral"


# ─── Rule-based fallback ───────────────────────────────────────────────────────

_WORKFLOW_PATTERNS: List[tuple] = [
    ("mri_preauth", [r"\bmri\b.*\bauth", r"\bpre[-\s]?auth.*\bmri"]),
    ("discharge_billing", [r"\bdischarge\b.*\bbilling", r"\bbilling.*\bdischarge"]),
    ("specimen_rejection", [r"\bspecimen\b.*\breject", r"\breject.*\bspecimen"]),
    ("it_his_access", [r"\b(it|his)\b.*\baccess\b", r"\baccess\b.*\b(his|system)\b"]),
]

_URGENCY_RE = re.compile(r"\b(urgent|asap|emergency|critical|immediate|stat)\b", re.I)
_NEG_RE = re.compile(r"\b(frustrated|wrong|broken|failed|terrible|angry|cannot|can't|didn't work)\b", re.I)
_POS_RE = re.compile(r"\b(great|perfect|thank|solved|excellent|helpful)\b", re.I)

_STATUS_RE = re.compile(r"\b(status|where is|what happened to|tracking)\b", re.I)
_COMPLAINT_RE = re.compile(r"\b(complaint|issue|problem|error|broken|wrong|bug)\b", re.I)
_SENSITIVE_RE = re.compile(r"\b(compliance|safety concern|HR|harassment|report|whistle)\b", re.I)

def _rule_based_intent(text: str) -> QueryIntent:
    low = text.lower()

    # urgency + sentiment
    urgency = "high" if _URGENCY_RE.search(text) else "normal"
    if _NEG_RE.search(text):
        sentiment = "neg"
    elif _POS_RE.search(text):
        sentiment = "pos"
    else:
        sentiment = "neutral"

    # workflow trigger
    for wf_id, patterns in _WORKFLOW_PATTERNS:
        for pat in patterns:
            if re.search(pat, low):
                return QueryIntent(
                    kind="start_workflow",
                    workflow_id=wf_id,
                    urgency=urgency,
                    sentiment=sentiment,
                )

    if _STATUS_RE.search(text):
        return QueryIntent(kind="status_check", urgency=urgency, sentiment=sentiment)
    if _SENSITIVE_RE.search(text):
        return QueryIntent(kind="sensitive_report", urgency=urgency, sentiment=sentiment)
    if _COMPLAINT_RE.search(text):
        return QueryIntent(kind="complaint", urgency=urgency, sentiment=sentiment)

    # Heuristic: question → knowledge question
    if "?" in text or re.search(r"\bwhat|how|when|where|who|why\b", low):
        return QueryIntent(kind="knowledge_question", urgency=urgency, sentiment=sentiment)

    return QueryIntent(kind="unclear", urgency=urgency, sentiment=sentiment)


# ─── LLM-powered understanding ──────────────────────────────────────────────

def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _parse_json_intent(raw: str) -> Optional[QueryIntent]:
    # Strip any accidental markdown fences
    raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`")
    try:
        data = json.loads(raw)
        # Coerce entities sub-dict
        if isinstance(data.get("entities"), dict):
            data["entities"] = QueryEntities(**{
                k: (v or None) for k, v in data["entities"].items()
                if k in {"insurer", "procedure", "department", "system"}
            })
        return QueryIntent(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("Intent JSON parse failed", error=str(e))
        return None


async def understand(
    text: str,
    llm,  # LLMPort instance
) -> QueryIntent:
    """
    Classifies user intent via the LLM (with one retry), then falls back to
    rule-based classification, then returns 'unclear'.
    """
    from app.llm.api import ModelTier

    system_prompt = _load_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]

    llm_result: Optional[QueryIntent] = None
    for attempt in range(2):
        try:
            resp = await llm.complete(messages, tier=ModelTier.FAST, json_mode=True, timeout=8.0)
            parsed = _parse_json_intent(resp.text)
            if parsed and parsed.kind != "unclear":
                return parsed
            if parsed:
                llm_result = parsed  # keep 'unclear' as candidate
            logger.warning("Intent parse returned unclear on attempt", attempt=attempt)
        except Exception as e:
            logger.warning("LLM understand attempt failed", attempt=attempt, error=str(e))

    # Rule-based fallback — always try it; prefer over LLM 'unclear'
    rule_result = _rule_based_intent(text)
    if rule_result.kind != "unclear":
        logger.info("Rule-based intent succeeded", kind=rule_result.kind)
        return rule_result

    # Both gave 'unclear' — return LLM result if we have one, else rule result
    if llm_result:
        return llm_result
    return rule_result
