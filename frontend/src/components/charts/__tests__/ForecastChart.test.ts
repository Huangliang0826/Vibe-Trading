import { describe, expect, it } from "vitest";

import { buildTradeOverlays } from "../ForecastChart";

describe("buildTradeOverlays", () => {
  it("anchors markers to displayed chart prices while retaining adjusted execution prices", () => {
    const bars = [
      { date: "2021-05-07", close: 1903, volume: 1 },
      { date: "2021-05-18", close: 2059.31, volume: 1 },
    ];
    const trades = [{
      entry_date: "2021-05-07", entry_price: 1683.315,
      exit_date: "2021-05-18", exit_price: 1767.2117,
      pnl_pct: 4.9, holding_bars: 7, exit_reason: "signal",
    }];

    const overlays = buildTradeOverlays(bars, trades);

    expect(overlays.entryData[0]).toMatchObject({
      value: ["2021-05-07", 1903], strategyPrice: 1683.315,
    });
    expect(overlays.exitData[0]).toMatchObject({
      value: ["2021-05-18", 2059.31], strategyPrice: 1767.2117,
    });
  });

  it("snaps a recent entry to the nearest bar when the chart history lags", () => {
    // Chart history ends 2026-07-24; the open position was entered 2026-07-28
    // (the strategy feed is fresher than the cached forecast cone).
    const bars = [
      { date: "2026-07-23", close: 27.14, volume: 1 },
      { date: "2026-07-24", close: 26.72, volume: 1 },
    ];
    const trades = [{
      entry_date: "2026-07-28", entry_price: 29.23,
      exit_date: "2026-07-29", exit_price: 29.26,
      pnl_pct: 0, holding_bars: 1, exit_reason: "end_of_backtest",
    }];

    const overlays = buildTradeOverlays(bars, trades);

    // Marker is drawn on the last available bar, but keeps the true trade date.
    expect(overlays.entryData[0]).toMatchObject({
      value: ["2026-07-24", 26.72], strategyPrice: 29.23, tradeDate: "2026-07-28",
    });
  });

  it("drops a marker whose date is far outside the displayed window", () => {
    const bars = [
      { date: "2026-07-23", close: 27.14, volume: 1 },
      { date: "2026-07-24", close: 26.72, volume: 1 },
    ];
    const trades = [{
      entry_date: "2025-01-06", entry_price: 40, // >7 days from any bar
      exit_date: "2025-01-20", exit_price: 42,
      pnl_pct: 5, holding_bars: 10, exit_reason: "signal",
    }];

    const overlays = buildTradeOverlays(bars, trades);
    expect(overlays.entryData).toEqual([]);
    expect(overlays.exitData).toEqual([]);
  });

  it("does not draw an artificial end-of-backtest exit", () => {
    const bars = [{ date: "2026-07-01", close: 1200, volume: 1 }];
    const trades = [{
      entry_date: "2026-07-01", entry_price: 1180,
      exit_date: "2026-07-02", exit_price: 1202,
      pnl_pct: 1, holding_bars: 1, exit_reason: "end_of_backtest",
    }];

    expect(buildTradeOverlays(bars, trades).exitData).toEqual([]);
  });
});
