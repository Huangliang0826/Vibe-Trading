import { expect, it } from "vitest";

import { comparisonChartSeries } from "../StrategyComparisonCharts";

it("builds aligned chart series and omits unavailable strategies", () => {
  const results = [
    { key: "spy_buy_hold", label: "SPY", status: "completed", points: [{ date: "2026-01-02", normalized: 1.1, drawdown: -.02, cash_ratio: 0, equity: 110, stock_exposure: 1 }] },
    { key: "defensive_momentum_v0", label: "V0", status: "unavailable", points: [] },
  ] as never;
  expect(comparisonChartSeries(results, "normalized")).toEqual([
    { name: "SPY", data: [["2026-01-02", 1.1]] },
  ]);
});
