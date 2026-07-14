import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  createStrategyComparison: vi.fn(), getStrategyComparison: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()), api: apiMock,
}));
vi.mock("../StrategyComparisonCharts", () => ({
  StrategyComparisonCharts: () => <div>比较图表</div>,
}));

import { StrategyComparisonTab } from "../StrategyComparisonTab";

const partialRun = {
  run_id: "comparison-20260713-120000-deadbeef", status: "partial",
  request: { start_date: "2021-07-13", end_date: "2026-07-13", initial_capital: 100000, cost_bps: 20 },
  created_at: "", updated_at: "", cache_key: "x", cache_hit: false,
  calculation_version: "paper-comparison.v1", survivorship_bias: true,
  universe_source_date: "2026-05-17", data_through: "2026-07-13",
  warnings: ["现金收益率按 0% 计算。"], error: null,
  scorecard: [{ key: "formal_validation", label: "正式验证", status: "unknown", detail: "存在幸存者偏差" }],
  results: [
    { key: "spy_buy_hold", label: "SPY 买入持有", status: "completed", coverage_rate: 1, error: null, points: [], metrics: { total_return: .2, cagr: .04, sharpe: .8, max_drawdown: -.1, calmar: .4, annual_vol: .15, worst_year: -.1, monthly_win_rate: .6, turnover: 1, transaction_cost: 20, average_cash_ratio: 0, minimum_cash_ratio: 0, annual_returns: {} } },
    { key: "defensive_momentum_v0", label: "防守型个股动量 Strategy V0", status: "unavailable", coverage_rate: 0, error: "panel down", points: [], metrics: null },
  ],
};

afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

it("defaults to five years and renders honest partial results", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-07-13T12:00:00Z"));
  apiMock.createStrategyComparison.mockResolvedValue(partialRun);
  render(<StrategyComparisonTab />);
  expect(screen.getByLabelText("开始日期")).toHaveValue("2021-07-13");
  expect(screen.getByLabelText("结束日期")).toHaveValue("2026-07-13");
  vi.useRealTimers();

  await userEvent.click(screen.getByRole("button", { name: "运行统一比较" }));

  expect(await screen.findByText("SPY 买入持有")).toBeInTheDocument();
  expect(screen.getByText(/存在幸存者偏差/)).toBeInTheDocument();
  expect(screen.getByText(/Strategy V0 暂不可用/)).toBeInTheDocument();
});
