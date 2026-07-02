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
