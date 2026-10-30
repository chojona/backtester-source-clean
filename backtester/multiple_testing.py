"""Family-wise attempt accounting for preregistered comparisons.

Bonferroni uses the larger of the preregistered family size and the number of
recorded attempts, so abandoned and failed variants still tighten the
threshold. A deterministic fixture never receives a significance claim.
"""
from __future__ import annotations


def effective_comparisons(planned_comparisons, attempt_count):
    if type(planned_comparisons) is not int or planned_comparisons < 1:
        raise ValueError("planned comparisons must be a positive integer")
    if type(attempt_count) is not int or attempt_count < 0:
        raise ValueError("attempt count must be a nonnegative integer")
    return max(planned_comparisons, attempt_count)


def compare_thresholds(p_value, *, attempt_count, planned_comparisons, alpha=0.05, sampling_model="none"):
    """Show unadjusted and Bonferroni thresholds without declaring significance."""
    if alpha != 0.05:
        raise ValueError("v1 adjustments use the preregistered alpha of 0.05")
    count = effective_comparisons(planned_comparisons, attempt_count)
    adjusted = alpha / count
    if sampling_model == "none":
        reason = "deterministic_fixture_has_no_sampling_model"
    else:
        reason = "sampling_model_is_not_a_historical_result"
    return {
        "p_value": p_value,
        "alpha": alpha,
        "attempt_count": attempt_count,
        "planned_comparisons": planned_comparisons,
        "effective_comparisons": count,
        "adjusted_alpha": adjusted,
        "adjustment": "bonferroni",
        "unadjusted_would_call_significant": p_value < alpha,
        "adjusted_would_call_significant": p_value < adjusted,
        "significance_claim": "refused",
        "reason": reason,
    }
