"""
Tests for recommender.py using known sample numbers we can verify by hand,
BEFORE trusting this logic against real Prometheus data.
"""

import pytest
from recommender import compute_p90, compute_recommendation, compute_waste_pct, build_report_row


def test_p90_known_sequence():
    # 90th percentile of 10..100 (step 10), linear interpolation (pandas default)
    # position = 0.9 * (10-1) = 8.1 -> between sorted[8]=90 and sorted[9]=100
    # => 90 + 0.1*(100-90) = 91
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert compute_p90(samples) == pytest.approx(91.0)


def test_recommendation_adds_20pct_buffer():
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    # p90 = 91, recommended = 91 * 1.2 = 109.2
    assert compute_recommendation(samples) == pytest.approx(109.2)


def test_waste_pct_cpu_example():
    # Mirrors app-1's design: requested 500m, actual usage low -> high waste
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    recommended = compute_recommendation(samples)
    waste = compute_waste_pct(requested=500, recommended=recommended)
    assert waste == pytest.approx(78.16, abs=0.01)


def test_waste_pct_memory_example():
    samples = [40, 42, 45, 50, 55, 48, 44, 46, 50, 52]
    recommended = compute_recommendation(samples)
    waste = compute_waste_pct(requested=256, recommended=recommended)
    assert waste == pytest.approx(75.48, abs=0.01)


def test_well_sized_pod_has_low_waste():
    # Mirrors app-4: recommended usage close to what was requested
    samples = [180, 190, 195, 200, 205, 195, 190, 200, 210, 205]
    recommended = compute_recommendation(samples)
    waste = compute_waste_pct(requested=250, recommended=recommended)
    # Should be a much smaller waste percentage than the CPU example above
    assert 0 <= waste < 30


def test_under_provisioned_pod_gives_negative_waste():
    # If actual usage recommendation EXCEEDS what was requested,
    # waste_pct should go negative -- flagging under-provisioning, not waste.
    samples = [400, 420, 450, 460, 470, 480, 490, 500, 510, 520]
    recommended = compute_recommendation(samples)  # p90=510, rec=612
    waste = compute_waste_pct(requested=500, recommended=recommended)
    assert waste < 0


def test_build_report_row_shape():
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    row = build_report_row("app-1", "cpu", requested=500, usage_samples=samples)
    assert row["pod"] == "app-1"
    assert row["resource"] == "cpu"
    assert row["requested"] == 500
    assert row["p90_actual"] == pytest.approx(91.0)
    assert row["recommended"] == pytest.approx(109.2)
    # build_report_row rounds waste_pct to 1 decimal place for display
    assert row["waste_pct"] == pytest.approx(78.2, abs=0.01)


def test_empty_samples_raises():
    with pytest.raises(ValueError):
        compute_p90([])
