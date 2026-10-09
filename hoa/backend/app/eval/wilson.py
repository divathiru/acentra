"""
Wilson 95% confidence interval calculation utilities.
"""

import math
from typing import Tuple


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Compute point estimate and Wilson 95% Confidence Interval for k successes in n trials.
    Returns (rate_percentage, lower_bound_pct, upper_bound_pct).
    """
    if n <= 0:
        return 0.0, 0.0, 0.0

    p = k / n
    z = 1.959964  # 95% confidence z-score
    z2 = z * z
    denom = 1 + z2 / n
    mid = (p + z2 / (2 * n)) / denom
    spread = (z / denom) * math.sqrt((p * (1 - p) / n) + (z2 / (4 * n * n)))

    lower = max(0.0, mid - spread) * 100.0
    upper = min(1.0, mid + spread) * 100.0
    rate = p * 100.0

    return round(rate, 1), round(lower, 1), round(upper, 1)


def format_wilson(k: int, n: int) -> str:
    """Format rate with 95% Wilson CI and sample size n."""
    rate, lower, upper = wilson_score_interval(k, n)
    return f"{rate:.1f}% [{lower:.1f}% - {upper:.1f}%] (n={n})"
