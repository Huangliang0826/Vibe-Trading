from src.analytics.quality_adapters import ForecastQualityAdapter, ScannerQualityAdapter


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
