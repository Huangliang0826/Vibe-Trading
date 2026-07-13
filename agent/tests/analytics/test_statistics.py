import pytest

from src.analytics.statistics import ewma, moving_median, robust_z_score, wilson_interval


def test_ewma_and_median_are_deterministic():
    assert ewma([10.0, 20.0, 20.0], alpha=0.3) == pytest.approx([10.0, 13.0, 15.1])
    assert moving_median([1.0, 100.0, 2.0], window=3) == [1.0, 50.5, 2.0]


def test_wilson_and_robust_z_handle_small_or_flat_samples():
    low, high = wilson_interval(15, 20)
    assert (low, high) == pytest.approx((0.5313, 0.8881), abs=1e-4)
    assert robust_z_score(9.0, [1, 2, 2, 2, 3, 2, 1]) > 3.5
    assert robust_z_score(2.0, [2, 2, 2, 2, 2, 2, 2]) == 0.0
