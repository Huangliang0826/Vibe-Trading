from datetime import date

from src.analytics.quality import make_quality_event
from src.analytics.statistics import bootstrap_interval


def test_quality_event_id_is_stable_per_observation():
    kwargs = dict(
        subject_type="forecast", subject_id="AAPL", market="us", horizon="63d",
        regime="all", metric_name="directional_accuracy", metric_value=0.56,
        sample_count=25, formula_version="forecast.calibration.v1", as_of=date(2026, 7, 13),
    )
    assert make_quality_event(**kwargs).event_id == make_quality_event(**kwargs).event_id


def test_seeded_bootstrap_is_repeatable():
    values = [0.01, 0.02, -0.01, 0.03, 0.0]
    first = bootstrap_interval(values, statistic="mean", resamples=2000, seed=1729)
    assert first == bootstrap_interval(values, statistic="mean", resamples=2000, seed=1729)
    assert first[0] <= sum(values) / len(values) <= first[1]
