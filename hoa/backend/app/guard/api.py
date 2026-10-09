"""Guard module for input/output sanitization and safety checks."""
import re
import unicodedata
import structlog
from typing import Tuple, Dict

logger = structlog.get_logger(__name__)

# ─── Pattern lists ─────────────────────────────────────────────────────────────

CLINICAL_PATTERNS = [
    r"\bdosage\b",
    r"\bdiagnosis\b",
    r"\binterpret\b.*\bresults?\b",
    r"\bresults?\b.*\binterpret\b",
    r"\b(read|analyze|review)\b.*\blab results?\b",
    r"\bshould (the|my|a) patient\b",
    r"\bmedication before\b",
    r"\bskip(ping)?\b.*\bmedication\b",
    r"\bstop(ping)?\b.*\bmedication\b",
    r"\bprescribe\b",
    r"\bwhat (is|should be) the treatment\b",
    r"\btreatment plan\b",
]

INJECTION_PATTERNS = [
    # Exact variations
    r"\bignore (all )?(previous |prior )?(rules|instructions|context|constraints)\b",
    r"\bforget (all )?(previous |prior )?(rules|instructions|context|constraints)\b",
    r"\bbypass (the |all )?(system|rules|safety|restrictions|filters)\b",
    r"\bact as (an )?admin(istrator)?\b",
    r"\bpretend (i |you )?(have|are|am)\b",
    r"\boverride( code)?s?\b",
    # Reveal / extract prompts
    r"\breveal\b.*\b(system prompt|prompt|instructions)\b",
    r"\b(system prompt|prompt)\b.*\breveal\b",
    r"\bshow me (the |your )?(system prompt|instructions|rules)\b",
    # Debug / mode switching
    r"\bdebug mode\b",
    r"\bdisable (all )?(safety|filters|restrictions)\b",
    # Role claim bypass
    r"\bshow me (all |restricted )?(documents|articles|data)\b.*\b(visibility|regardless)\b",
    r"\bignore (the )?(role|rbac|visibility|access) (check|control|rule)\b",
]

RBAC_BYPASS_PATTERNS = [
    r"\bshow (me |us )?(all|restricted|hidden) (documents|articles|data|content)\b",
    r"\bgrant (me|us) (all |full |admin )?access\b",
    r"\bpretend (i have|you gave me|i am)\b",
]

PHI_PATTERNS = {
    "MRN": r"\b(?:MRN|mrn|Patient[\s_]?ID)[-:\s]*([A-Z0-9]{5,10})\b",
    "PHONE": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize unicode to ASCII lookalike equivalents for confusable detection."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def scan_input(text: str) -> Tuple[bool, str, Dict[str, str]]:
    """
    Scans input for clinical questions and injections. Returns (safe, sanitized_text, vault).
    Fails closed: any exception → REFUSE.
    """
    try:
        # Check both original (for PHI extraction) and normalized (for confusable attacks)
        text_lower = text.lower()
        text_norm = _normalize(text).lower()

        # Clinical check on both representations
        for pattern in CLINICAL_PATTERNS:
            if re.search(pattern, text_lower) or re.search(pattern, text_norm):
                return False, text, {}

        # Injection check on both representations
        all_injection = INJECTION_PATTERNS + RBAC_BYPASS_PATTERNS
        for pattern in all_injection:
            if re.search(pattern, text_lower) or re.search(pattern, text_norm):
                return False, text, {}

        # PHI replacement (only after safety checks pass)
        vault: Dict[str, str] = {}
        sanitized_text = text
        phi_counters: Dict[str, list] = {k: [1] for k in PHI_PATTERNS}

        for p_type, pattern in PHI_PATTERNS.items():
            idx = phi_counters[p_type]

            def replacer(match, _type=p_type, _idx=idx):
                raw_val = match.group(0)
                placeholder = f"<{_type}_{_idx[0]}>"
                vault[placeholder] = raw_val
                _idx[0] += 1
                return placeholder

            sanitized_text = re.sub(pattern, replacer, sanitized_text)

        return True, sanitized_text, vault

    except Exception as e:
        logger.error("Guard module exception in scan_input", error=str(e))
        return False, text, {}


def scan_retrieval(text: str) -> bool:
    """Scans retrieved text for prompt injections."""
    try:
        text_lower = text.lower()
        text_norm = _normalize(text).lower()
        all_injection = INJECTION_PATTERNS + RBAC_BYPASS_PATTERNS
        for pattern in all_injection:
            if re.search(pattern, text_lower) or re.search(pattern, text_norm):
                return False
        return True
    except Exception as e:
        logger.error("Guard module exception in scan_retrieval", error=str(e))
        return False


def scan_output(text: str, vault: Dict[str, str]) -> bool:
    """Scans output to ensure no raw identifiers leaked."""
    try:
        for raw_val in vault.values():
            if raw_val in text:
                return False
        return True
    except Exception as e:
        logger.error("Guard module exception in scan_output", error=str(e))
        return False
