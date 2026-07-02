import { describe, expect, it } from "vitest";

import { recentSignalsFromBestStrategies } from "../Forecast";

function stateWithTrades(trades: Record<string, unknown>[]) {
  return {
    "us:NVDA": {
      loading: false,
      error: null,
      data: {
        code: "NVDA",
        name: "NVIDIA",
        best: {
          strategy: { name: "buy_and_hold", label: "买入持有" },
          trades,
        },
      },
    },
  } as never;
}

function stateWithTrade(trade: Record<string, unknown>) {
  return stateWithTrades([trade]);
}

describe("recentSignalsFromBestStrategies", () => {
  it("does not report an end-of-backtest close as a strategy exit", () => {
    const states = stateWithTrade({
      entry_date: "2020-01-03",
      exit_date: "2026-07-01",
      entry_price: 10,
      exit_price: 100,
      pnl_pct: 900,
      exit_reason: "end_of_backtest",
    });

    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], states, "2026-06-25",
    )).toEqual([]);
  });

  it("keeps recent entries and genuine strategy exits", () => {
    const recentEntry = stateWithTrade({
      entry_date: "2026-07-01", exit_date: "2026-07-02",
      entry_price: 100, exit_price: 101, pnl_pct: 1,
      exit_reason: "end_of_backtest",
    });
    const genuineExit = stateWithTrade({
      entry_date: "2026-06-01", exit_date: "2026-07-02",
      entry_price: 90, exit_price: 100, pnl_pct: 11.1,
      exit_reason: "signal",
    });

    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], recentEntry, "2026-06-25",
    )).toHaveLength(1);
    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], recentEntry, "2026-06-25",
    )[0].action).toBe("开仓");
    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], genuineExit, "2026-06-25",
    )[0].action).toBe("平仓");
  });

  it("shows the reopened position after a same-day rebalance", () => {
    const states = stateWithTrades([
      {
        entry_date: "2026-06-29", exit_date: "2026-07-02",
        entry_price: 100, exit_price: 101, pnl_pct: 1, exit_reason: "rebalance",
      },
      {
        entry_date: "2026-07-02", exit_date: "2026-07-02",
        entry_price: 101, exit_price: 101, pnl_pct: 0, exit_reason: "end_of_backtest",
      },
    ]);

    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], states, "2026-06-25",
    )[0].action).toBe("开仓");
  });

  it("suppresses signals from a strategy that failed OOS validation", () => {
    const states = stateWithTrade({
      entry_date: "2026-07-01", exit_date: "2026-07-02",
      entry_price: 100, exit_price: 101, pnl_pct: 1, exit_reason: "signal",
    }) as unknown as Record<string, { data: { reliable: boolean } }>;
    states["us:NVDA"].data.reliable = false;

    expect(recentSignalsFromBestStrategies(
      [{ market: "us", code: "NVDA" }], states as never, "2026-06-25",
    )).toEqual([]);
  });
});
