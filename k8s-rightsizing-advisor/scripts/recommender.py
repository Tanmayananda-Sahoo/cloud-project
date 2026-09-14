"""
Core right-sizing recommendation logic.

Deliberately has zero Prometheus/network dependency so it can be
tested against known numbers in isolation.
"""

import pandas as pd


SAFETY_BUFFER = 0.20  # 20% headroom on top of the 90th percentile
PERCENTILE = 0.90


def compute_p90(usage_samples):
    """
    Given a list/Series of historical usage samples (e.g. CPU millicores
    or memory bytes sampled over time), return the 90th percentile.
    """
    series = pd.Series(usage_samples)
    if series.empty:
        raise ValueError("No usage samples provided — cannot compute a percentile")
    return series.quantile(PERCENTILE)


def compute_recommendation(usage_samples, buffer=SAFETY_BUFFER):
    """
    Returns the recommended value: p90 usage + safety buffer.
    """
    p90 = compute_p90(usage_samples)
    return p90 * (1 + buffer)


def compute_waste_pct(requested, recommended):
    """
    How much of the requested value is unused, as a percentage.
    Negative means the pod is actually under-provisioned (recommended > requested).
    """
    if requested <= 0:
        raise ValueError("Requested value must be positive")
    return (requested - recommended) / requested * 100


def build_report_row(pod_name, resource, requested, usage_samples, buffer=SAFETY_BUFFER):
    """
    Produces one row of the final report for a given pod + resource (cpu or memory).
    """
    p90 = compute_p90(usage_samples)
    recommended = p90 * (1 + buffer)
    waste_pct = compute_waste_pct(requested, recommended)
    return {
        "pod": pod_name,
        "resource": resource,
        "requested": round(requested, 2),
        "p90_actual": round(p90, 2),
        "recommended": round(recommended, 2),
        "waste_pct": round(waste_pct, 1),
    }
