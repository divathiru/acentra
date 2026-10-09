"""Knowledge verification logic."""

from app.knowledge.api import EvidenceBundle

def _clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(val, max_val))

def verify_evidence(bundle: EvidenceBundle, expected_entities: int, resolved_entities: int, config: dict) -> dict:
    """
    Evaluates the quality of retrieved evidence based on coverage, semantic similarity, and entity resolution.
    
    Returns a dict with:
        - score: float in [0, 1]
        - band: str ('high', 'medium', 'low')
        - conflict: bool
        - coverage: dict of coverage boolean flags
        - reasons: list of strings
    """
    
    nodes_attr = getattr(bundle, "nodes", None)
    if nodes_attr is not None and not nodes_attr:
        return {
            "score": 0.0,
            "band": "low",
            "conflict": False,
            "coverage": {k: False for k in ["WHAT", "WHERE", "NEXT", "WHO", "HOW"]},
            "reasons": ["No relevant evidence nodes found"]
        }

    cov = {
        "WHAT": any(e["type"] == "defined_in" for e in bundle.edges),
        "WHERE": any(e["type"] in ["requires_form", "performed_in"] for e in bundle.edges),
        "NEXT": any(e["type"] in ["has_step", "escalates_to"] for e in bundle.edges),
        "WHO": any(e["type"] in ["owned_by", "escalates_to"] for e in bundle.edges),
        "HOW": any(e["type"] == "requires" for e in bundle.edges)
    }
    
    coverage_score = sum(cov.values()) / 5.0
    
    sim = _clamp((bundle.top1_cosine - 0.30) / 0.50, 0.0, 1.0)
    
    if expected_entities <= 0:
        entity_score = 1.0
    else:
        entity_score = _clamp(resolved_entities / float(expected_entities), 0.0, 1.0)
        
    # Read weights and cut-offs from config (or use defaults)
    w_sim = config.get("verify_weight_sim", 0.40)
    w_cov = config.get("verify_weight_cov", 0.40)
    w_ent = config.get("verify_weight_ent", 0.20)
    
    score = w_sim * sim + w_cov * coverage_score + w_ent * entity_score
    
    band_high = config.get("verify_band_high", 0.70)
    band_medium = config.get("verify_band_medium", 0.45)
    
    if score >= band_high and sim >= 0.3:
        band = "high"
    elif score >= band_medium and (sim >= 0.25 or coverage_score > 0):
        band = "medium"
    else:
        band = "low"
        
    reasons = [
        f"Similarity score: {sim:.2f}",
        f"Coverage score: {coverage_score:.2f} ({sum(cov.values())}/5)",
        f"Entity score: {entity_score:.2f} ({resolved_entities}/{expected_entities})"
    ]
    if bundle.conflict_flag:
        reasons.append(f"Conflict detected between owners: {', '.join(bundle.conflict_owners)}")
        
    return {
        "score": score,
        "band": band,
        "conflict": bundle.conflict_flag,
        "coverage": cov,
        "reasons": reasons
    }
