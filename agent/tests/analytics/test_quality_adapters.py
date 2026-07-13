from datetime import date
from types import SimpleNamespace

from src.analytics.quality_adapters import (
    BacktestQualityAdapter,
    ForecastQualityAdapter,
    PaperTradingQualityAdapter,
    ScannerQualityAdapter,
)


def test_scanner_adapter_maps_each_horizon_without_recomputing(monkeypatch):
    monkeypatch.setattr("src.analytics.quality_adapters.load_all_tracking", lambda universe: [object()])
    monkeypatch.setattr("src.analytics.quality_adapters.compute_accuracy", lambda records, provider=None: {
        "horizons": {"fwd_5d": {"n": 40, "mean": 1.2, "hit_rate": 0.575, "spread": 0.8}},
        "timeseries": [],
    })
    events = ScannerQualityAdapter().collect("sp500")
    values = {(event.metadata["horizon"], event.metadata["metric_name"]): event.metadata["metric_value"] for event in events}
    assert values[("5d", "hit_rate")] == 0.575
    assert values[("5d", "mean_forward_return_pct")] == 1.2
    assert values[("5d", "top_bottom_spread_pct")] == 0.8


def test_forecast_adapter_maps_calibration_payload():
    payload = {
        "code": "AAPL", "market": "us", "bt_horizon": 63,
        "directional_accuracy": {"model": 0.56, "n": 25},
        "mae": {"model": 3.2}, "interval_coverage_80": 0.76,
        "interval_score_skill": 0.11, "mean_interval_width_pct": 8.4,
    }
    events = ForecastQualityAdapter().from_calibration(payload)
    by_metric = {event.metadata["metric_name"]: event for event in events}
    assert by_metric["directional_accuracy"].metadata["metric_value"] == 0.56
    assert by_metric["mae"].metadata["metric_value"] == 3.2
    assert all(event.metadata["formula_version"] == "forecast.calibration.v1" for event in events)
    assert all(event.metadata["subject_id"] == "AAPL" for event in events)
    assert all(event.metadata["sample_count"] == 25 for event in events)


def test_backtest_adapter_preserves_authoritative_metrics():
    events = BacktestQualityAdapter().from_metrics(
        run_id="run-1",
        market="us",
        as_of=date(2026, 7, 12),
        metrics={
            "total_return": 0.21,
            "sharpe": 1.4,
            "max_drawdown": -0.12,
            "trade_count": 31,
            "ignored": 123,
        },
    )

    values = {
        event.metadata["metric_name"]: event.metadata["metric_value"]
        for event in events
    }
    assert values == {
        "total_return": 0.21,
        "sharpe": 1.4,
        "max_drawdown": -0.12,
        "trade_count": 31.0,
    }
    assert all(event.metadata["sample_count"] == 31 for event in events)


def test_paper_adapter_uses_completion_date_and_metric_version():
    run = SimpleNamespace(
        run_id="paper-1",
        updated_at="2026-07-12T14:30:00Z",
        holdings=[SimpleNamespace(market="us")],
        experiment=SimpleNamespace(metric_version="backtest.metrics.v2"),
        metrics={"total_return": 0.15, "trade_count": 24},
    )

    events = PaperTradingQualityAdapter().from_run(run)

    assert {event.metadata["as_of"] for event in events} == {"2026-07-12"}
    assert {event.metadata["subject_type"] for event in events} == {"paper_trading"}
    assert all(
        event.metadata["formula_version"] == "paper.backtest.metrics.v2"
        for event in events
    )
    assert all(event.metadata["sample_count"] == 24 for event in events)
