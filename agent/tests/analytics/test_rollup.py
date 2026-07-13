from datetime import date

from src.analytics.rollup import AnalyticsRollup
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


def test_daily_rollup_is_idempotent_and_keeps_fraction_inputs(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    events = [
        _event("a"),
        _event("b").model_copy(update={"action": "task_start"}),
        _event("c").model_copy(update={"action": "task_complete"}),
        _event("d").model_copy(update={"action": "task_complete", "outcome": "failure"}),
    ]
    store.append_events(events)
    rollup = AnalyticsRollup(store)
    rollup.run_day(date(2026, 7, 13))
    rollup.run_day(date(2026, 7, 13))
    points = store.query_metric_points(metric="task_success_rate")
    assert len(points) == 1
    assert (points[0].numerator, points[0].denominator, points[0].value) == (1, 2, 0.5)
