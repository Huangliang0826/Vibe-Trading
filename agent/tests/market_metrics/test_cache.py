from __future__ import annotations

from datetime import date

from src.market_metrics.cache import MarketMetricsCache, make_cache_key
from src.market_metrics.models import MarketBar
from src.market_metrics.service import build_market_metrics_response


def _response(*, invalid: bool = False):
    first = (
        MarketBar("2025-01-02", 100.0, 90.0, 99.0, 100.0, 1_000)
        if invalid else MarketBar("2025-01-02", 100.0, 100.0, 100.0, 100.0, 1_000)
    )
    return build_market_metrics_response(
        symbol="AAPL",
        market="us",
        currency="USD",
        period="1Y",
        requested_start=date(2025, 1, 3),
        bars=[first, MarketBar("2025-01-03", 110.0, 110.0, 110.0, 110.0, 1_200)],
        source="fixture",
    )


def test_formula_version_invalidates_cached_metrics(tmp_path):
    cache = MarketMetricsCache(tmp_path, formula_version="v1")
    key = make_cache_key("us", "AAPL", "1Y", "adjusted")
    assert cache.put(key, _response(), source_revision="2026-07-03") is True

    assert cache.get(key, source_revision="2026-07-03") is not None
    assert MarketMetricsCache(tmp_path, formula_version="v2").get(
        key, source_revision="2026-07-03",
    ) is None


def test_source_revision_invalidates_cached_metrics(tmp_path):
    cache = MarketMetricsCache(tmp_path)
    key = make_cache_key("hk", "0700.HK", "1Y", "adjusted")
    cache.put(key, _response(), source_revision="2026-07-03")

    assert cache.get(key, source_revision="2026-07-04") is None


def test_invalid_response_does_not_replace_valid_cache(tmp_path):
    cache = MarketMetricsCache(tmp_path)
    key = make_cache_key("us", "AAPL", "1Y", "adjusted")
    cache.put(key, _response(), source_revision="rev")

    assert cache.put(key, _response(invalid=True), source_revision="rev") is False
    loaded = cache.get(key, source_revision="rev")
    assert loaded is not None
    assert loaded.data_status.quality == "valid"


def test_malformed_cache_is_a_miss(tmp_path):
    cache = MarketMetricsCache(tmp_path)
    key = make_cache_key("us", "AAPL", "1Y", "adjusted")
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert cache.get(key, source_revision="rev") is None

