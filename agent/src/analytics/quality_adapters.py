from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping

from src.scanner.tracking import compute_accuracy, load_all_tracking

from .models import AnalyticsEvent
from .quality import make_quality_event
from .statistics import bootstrap_interval, wilson_interval


def _finite(value: object) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


class ScannerQualityAdapter:
    def collect(self, universe: str, provider: str | None = None) -> list[AnalyticsEvent]:
        records = load_all_tracking(universe=universe)
        market = {"sp500": "us", "hstech": "hk"}.get(universe, universe)
        dates = [getattr(record, "asof", None) for record in records]
        as_of = date.fromisoformat(max(value for value in dates if value)) if any(dates) else date.today()
        return self.from_records(
            records,
            market=market,
            subject_id=provider or "all",
            as_of=as_of,
            provider=provider,
        )

    def from_records(
        self,
        records: list[Any],
        *,
        market: str,
        subject_id: str,
        as_of: date,
        provider: str | None = None,
    ) -> list[AnalyticsEvent]:
        payload = compute_accuracy(records, provider=provider)
        events: list[AnalyticsEvent] = []
        mapping = {
            "mean": "mean_forward_return_pct",
            "hit_rate": "hit_rate",
            "spread": "top_bottom_spread_pct",
            "ic": "rank_ic",
        }
        for field, summary in payload.get("horizons", {}).items():
            horizon = field.removeprefix("fwd_")
            sample_count = int(summary.get("n") or 0)
            raw_values = [
                float(value)
                for record in records
                if (value := getattr(record, field, None)) is not None
                and isinstance(value, (int, float))
                and math.isfinite(value)
            ]
            for source_name, metric_name in mapping.items():
                value = _finite(summary.get(source_name))
                if value is None:
                    continue
                low = high = None
                if source_name == "hit_rate" and sample_count:
                    if value > 1:
                        value /= 100
                    low, high = wilson_interval(round(value * sample_count), sample_count)
                elif source_name == "mean" and len(raw_values) >= 2:
                    low, high = bootstrap_interval(raw_values, statistic="mean")
                events.append(make_quality_event(
                    subject_type="scanner",
                    subject_id=subject_id,
                    market=market,
                    horizon=horizon,
                    regime="all",
                    metric_name=metric_name,
                    metric_value=value,
                    sample_count=sample_count,
                    formula_version="scanner.accuracy.v1",
                    as_of=as_of,
                    interval_low=low,
                    interval_high=high,
                ))
        return events


class ForecastQualityAdapter:
    def from_calibration(self, payload: Mapping[str, Any]) -> list[AnalyticsEvent]:
        subject_id = str(payload.get("code") or "unknown").upper()
        market = str(payload.get("market") or "unknown").lower()
        horizon_days = int(payload.get("bt_horizon") or 0)
        horizon = f"{horizon_days}d" if horizon_days else "unknown"
        directional = payload.get("directional_accuracy") or {}
        sample_count = int(directional.get("n") or payload.get("sample_count") or 0)
        raw = {
            "directional_accuracy": directional.get("model"),
            "mae": (payload.get("mae") or {}).get("model"),
            "interval_coverage_80": payload.get("interval_coverage_80"),
            "interval_score_skill": payload.get("interval_score_skill"),
            "mean_interval_width_pct": payload.get("mean_interval_width_pct"),
        }
        as_of_raw = payload.get("as_of")
        try:
            as_of = date.fromisoformat(str(as_of_raw)) if as_of_raw else date.today()
        except ValueError:
            as_of = date.today()
        events: list[AnalyticsEvent] = []
        for metric_name, raw_value in raw.items():
            value = _finite(raw_value)
            if value is None:
                continue
            low = high = None
            if metric_name in {"directional_accuracy", "interval_coverage_80"} and sample_count:
                low, high = wilson_interval(round(value * sample_count), sample_count)
            events.append(make_quality_event(
                subject_type="forecast",
                subject_id=subject_id,
                market=market,
                horizon=horizon,
                regime="all",
                metric_name=metric_name,
                metric_value=value,
                sample_count=sample_count,
                formula_version="forecast.calibration.v1",
                as_of=as_of,
                interval_low=low,
                interval_high=high,
            ))
        return events


SCALAR_METRICS = (
    "total_return",
    "total_return_pct",
    "annual_return",
    "annual_return_pct",
    "sharpe",
    "max_loss",
    "max_drawdown",
    "win_rate",
    "trade_count",
)


class BacktestQualityAdapter:
    def from_metrics(
        self,
        *,
        run_id: str,
        market: str,
        as_of: date,
        metrics: Mapping[str, Any],
        formula_version: str = "backtest.metrics.v2",
    ) -> list[AnalyticsEvent]:
        trade_count = _finite(metrics.get("trade_count"))
        sample_count = max(1, int(trade_count or 1))
        events: list[AnalyticsEvent] = []
        for metric_name in SCALAR_METRICS:
            value = _finite(metrics.get(metric_name))
            if value is None:
                continue
            events.append(make_quality_event(
                subject_type="backtest",
                subject_id=run_id,
                market=market,
                horizon="run",
                regime="all",
                metric_name=metric_name,
                metric_value=value,
                sample_count=sample_count,
                formula_version=formula_version,
                as_of=as_of,
            ))
        return events


class PaperTradingQualityAdapter:
    def from_run(self, run: Any) -> list[AnalyticsEvent]:
        updated_at = str(getattr(run, "updated_at", ""))
        as_of = date.fromisoformat(updated_at[:10])
        holdings = getattr(run, "holdings", ()) or ()
        markets = {str(getattr(holding, "market", "unknown")) for holding in holdings}
        market = next(iter(markets)) if len(markets) == 1 else "multi"
        experiment = getattr(run, "experiment", None)
        metric_version = str(getattr(experiment, "metric_version", "backtest.metrics.v2"))
        return BacktestQualityAdapter().from_metrics(
            run_id=str(run.run_id),
            market=market,
            as_of=as_of,
            metrics=getattr(run, "metrics", None) or {},
            formula_version=f"paper.{metric_version}",
        )
