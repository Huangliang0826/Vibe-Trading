import { describe, expect, it } from "vitest";
import { buildRobustWinnerRunRequest } from "../paper-trading-robust";

describe("buildRobustWinnerRunRequest", () => {
  it("builds a normal backtest request from the robust winner and current form", () => {
    const holdings = [{ symbol: "AAPL", market: "us" as const, allocation_pct: 100 }];

    expect(buildRobustWinnerRunRequest({
      bestStrategy: "deep_drawdown_recovery",
      winnerParams: { core_position_pct: 0.25, tranches: 10 },
      holdings,
      startDate: "2020-01-01",
      endDate: "2026-07-03",
      initialUsd: 100_000,
      initialHkd: 1_000_000,
    })).toEqual({
      title: "多时间段最稳健 - deep_drawdown_recovery",
      holdings,
      strategy: {
        name: "deep_drawdown_recovery",
        params: { core_position_pct: 0.25, tranches: 10 },
      },
      start_date: "2020-01-01",
      end_date: "2026-07-03",
      initial_usd: 100_000,
      initial_hkd: 1_000_000,
    });
  });

  it("rejects a missing robust winner", () => {
    expect(() => buildRobustWinnerRunRequest({
      bestStrategy: null,
      winnerParams: {},
      holdings: [],
      startDate: "2020-01-01",
      endDate: "2026-07-03",
      initialUsd: 100_000,
      initialHkd: 1_000_000,
    })).toThrow("No robust winner available");
  });
});
