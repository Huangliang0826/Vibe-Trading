from datetime import date, timedelta

import pandas as pd
import pytest

import api_server


class RecordingRuntime:
    def __init__(self):
        self.calls = []

    def observe_provider(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class Loader:
    def __init__(self, frame=None, error=None):
        self.frame = frame
        self.error = error

    def fetch(self, *, codes, start_date, end_date, interval):
        if self.error:
            raise self.error
        return {codes[0]: self.frame}


def test_price_history_observes_success_without_changing_result(monkeypatch):
    today = date.today()
    frame = pd.DataFrame(
        {"close": [100.0, 101.0], "volume": [1_000, 1_100]},
        index=pd.to_datetime([today - timedelta(days=1), today]),
    )
    runtime = RecordingRuntime()
    monkeypatch.setattr(api_server, "_analytics_runtime", runtime)
    monkeypatch.setattr("backtest.loaders.registry.resolve_loader", lambda _market: Loader(frame))
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda _code, _market: "Test")

    result = api_server._fetch_price_history("NVDA", "1Y", "us")

    assert result["name"] == "Test"
    assert len(result["bars"]) == 2
    assert runtime.calls[0][0][2] == "success"
    assert runtime.calls[0][0][4:6] == (1, 1)


def test_price_history_observes_failure_and_preserves_exception(monkeypatch):
    runtime = RecordingRuntime()
    monkeypatch.setattr(api_server, "_analytics_runtime", runtime)
    monkeypatch.setattr(
        "backtest.loaders.registry.resolve_loader",
        lambda _market: Loader(error=RuntimeError("provider unavailable")),
    )
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda _code, _market: "Test")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        api_server._fetch_price_history("NVDA", "1Y", "us")

    assert runtime.calls[0][0][2] == "failure"
    assert runtime.calls[0][1]["error_code"] == "RuntimeError"
