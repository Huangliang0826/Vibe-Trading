# Unified Market Metrics Engine Design

## Goal

Make every price chart and return metric in Vibe-Trading use the same verified
market data and formulas. The first release covers adjusted prices, interval
returns, volume, daily-DCA returns, maximum loss, and maximum drawdown for US,
Hong Kong, and A-share instruments.

The work prioritizes correctness and explainability over adding strategies. A
metric must not be displayed as valid when its source data or required baseline
is missing.

## Decisions

- Adjusted prices are the default basis for historical charts and returns.
- The latest raw market quote is stored separately from adjusted history.
- Maximum loss and maximum drawdown are distinct metrics.
- Interval returns use the standard market baseline convention.
- The backend is the only owner of financial metric calculations.
- Every result carries a formula version and data-quality metadata.

## Architecture

Introduce a backend `MarketMetricsEngine` as the single calculation boundary.
It accepts:

- canonical symbol and market;
- exchange timezone and trading calendar;
- requested date range;
- adjusted OHLCV history;
- optional investment cash flows.

It returns a stable response containing:

- chart-ready adjusted price series;
- raw latest quote when available;
- volume series in the exchange-provided unit;
- interval return and its explicit baseline/end observations;
- daily-DCA return;
- daily-DCA maximum loss;
- buy-and-hold maximum loss;
- maximum drawdown as a separate field;
- source, market timestamp, cache timestamp, adjustment mode, and formula
  version;
- machine-readable quality status and user-facing warnings.

Frontend pages format and render this response but do not recompute returns,
losses, drawdowns, or DCA account values. Overview, Forecast, HSTech, and Paper
Trading migrate to the contract in stages.

The data flow is:

`fetch -> canonicalize -> adjust -> validate -> cache -> calculate -> API -> UI`

## Calculation Contract

### Prices and interval returns

- Historical return calculations use adjusted close.
- `1D` return is measured from the previous official adjusted close to the
  latest available compatible price.
- `1M`, `YTD`, `1Y`, `3Y`, `5Y`, and `ALL` use the adjusted close from the last
  trading session before the requested range as the baseline and the latest
  compatible price as the endpoint.
- The response includes the baseline date, baseline value, endpoint date, and
  endpoint value so the result can be independently checked.
- If the required baseline is unavailable, the engine returns an unavailable
  metric with a reason. It must not silently shorten the range.
- Raw intraday quotes and adjusted historical closes may only be combined when
  the provider supplies a compatible adjustment factor. Otherwise, the last
  adjusted close remains the endpoint and the response identifies its timestamp.

### Daily DCA

- One equal cash contribution is invested on every trading day in the selected
  range at that day's adjusted close.
- Fractional shares are allowed for this analytical chart metric.
- At time `t`, DCA return is:

  `(account_value_t - cumulative_contributions_t) / cumulative_contributions_t`

- Daily-DCA maximum loss is the minimum value of that return series.
- Contributions, accumulated units, account value, and return series are
  calculated by the engine from one shared cash-flow ledger.

### Maximum loss and drawdown

- Maximum loss is the minimum account return relative to cumulative invested
  capital. For buy and hold, invested capital is the initial investment. For
  DCA or a portfolio, it is cumulative external contributions through each date.
- Maximum drawdown is the largest decline from a prior account-value peak.
- The fields and labels remain separate throughout models, APIs, and UI. Neither
  may be substituted for the other.

### Volume

- Volume remains in the original exchange/provider unit and is not filled with
  zero when absent.
- Missing observations remain null and produce a quality warning.
- Split handling must preserve provider semantics; price adjustment must not
  manufacture adjusted volume unless the provider explicitly supplies it.

## Data Quality

Validation runs before metrics are calculated. It checks:

- duplicate, unsorted, or invalid timestamps;
- non-positive prices and invalid OHLC relationships;
- missing or negative volume;
- unexplained trading-session gaps;
- stale latest observations;
- missing interval baseline sessions;
- discontinuities inconsistent with known adjustment data;
- mixed symbols, markets, currencies, or adjustment modes.

Quality has three states:

- `valid`: calculations may be displayed normally;
- `warning`: calculations may be displayed with explicit warnings and affected
  fields identified;
- `invalid`: affected calculations are unavailable and carry reason codes.

The engine never turns an HTML error response, empty provider response, or
partial payload into a valid cached dataset.

## Caching and Versioning

Use two cache layers:

1. Canonical OHLCV cache keyed by canonical symbol, market, date range, provider,
   adjustment mode, and source revision.
2. Metrics cache keyed by canonical data identity, requested range, cash-flow
   parameters, and `formula_version`.

Completed historical sessions can be retained long-term. The current session
uses market-aware freshness rules. A new source observation, corporate-action
revision, adjustment-mode change, or formula-version change invalidates affected
metrics automatically.

Cache entries are written atomically and include source timestamp, fetch time,
validation result, and content identity. Failed or invalid fetches do not replace
the last known valid entry.

## API Contract

The exact route may follow the existing market-data router, but all consumers use
one typed payload. At minimum it includes:

```json
{
  "symbol": "AAPL",
  "market": "US",
  "currency": "USD",
  "range": "1Y",
  "adjustment": "adjusted",
  "formula_version": "market-metrics-v1",
  "series": [],
  "volume": [],
  "metrics": {
    "interval_return_pct": null,
    "dca_return_pct": null,
    "dca_max_loss_pct": null,
    "buy_hold_max_loss_pct": null,
    "max_drawdown_pct": null
  },
  "baseline": {},
  "data_status": {
    "quality": "valid",
    "source": "provider-name",
    "data_through": "2026-07-03T20:00:00Z",
    "cached_at": "2026-07-04T08:00:00Z",
    "warnings": []
  }
}
```

Unavailable numeric values are `null`, never fabricated zeroes. Reason codes are
included alongside unavailable fields in the concrete schema.

## Migration

### Phase 1: Overview and shared price charts

Move interval return, daily-DCA return, daily-DCA maximum loss, buy-and-hold
maximum loss, and volume to the engine. Remove equivalent frontend formulas.

### Phase 2: Forecast and HSTech

Use the same adjusted series and metric payload. Align strategy entry/exit
markers with the exact price series and timestamps rendered by the chart.

### Phase 3: Paper Trading and backtests

Move portfolio cash-flow accounting, account return, maximum loss, and maximum
drawdown to shared calculation primitives. Preserve strategy execution logic as
a separate concern from market-data and performance measurement.

Each phase is independently releasable and keeps compatibility adapters until
all consumers have migrated.

## Testing and Acceptance

Unit fixtures use small hand-calculated datasets to prove exact results for:

- every supported interval;
- missing baseline sessions;
- dividends and splits;
- daily contributions and fractional units;
- external cash flows;
- maximum loss versus maximum drawdown;
- missing volume and invalid OHLC rows;
- timezone and non-trading-day boundaries.

Integration fixtures cover:

- US ordinary, dividend, and split instruments;
- Hong Kong ordinary shares, ETFs, and suspended or sparse instruments;
- A-share adjusted history and holiday boundaries.

Acceptance criteria:

1. The same symbol, range, and data revision produce identical metrics on every
   page.
2. `1D` and longer ranges expose and use the agreed baseline observations.
3. Daily-DCA results match independently hand-calculated fixtures.
4. Maximum loss and maximum drawdown remain separately correct in fixtures where
   they differ.
5. Missing or invalid data cannot produce a valid-looking zero or percentage.
6. Formula-version changes invalidate metric caches.
7. A repository check rejects new frontend implementations of financial metric
   formulas after migration.

## Non-Goals

- Adding new trading strategies or predictive models.
- Building a full tick-data warehouse.
- Changing strategy selection or execution rules.
- Guaranteeing identical values across unrelated external vendors; differences
  must instead be attributable through source and adjustment metadata.
