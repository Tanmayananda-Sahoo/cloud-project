import pytest
from cost_estimator import monthly_cost


def test_cpu_cost_known_value():
    # 500m = 0.5 vCPU * $0.04048/hr * 730 hrs = $14.7752
    assert monthly_cost(500, "cpu") == pytest.approx(14.7752, abs=0.001)


def test_memory_cost_known_value():
    # 256Mi = 0.25 GB * $0.004445/hr * 730 hrs = $0.8112
    assert monthly_cost(256, "memory") == pytest.approx(0.8112, abs=0.001)


def test_double_resources_double_cost():
    assert monthly_cost(1000, "cpu") == pytest.approx(2 * monthly_cost(500, "cpu"))


def test_unknown_resource_raises():
    with pytest.raises(ValueError):
        monthly_cost(100, "gpu")
