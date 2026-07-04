import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/echarts", () => ({
  echarts: {
    init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
  },
}));

import { PriceHistoryChart } from "../PriceHistoryChart";
import type { WatchlistHistoryResponse } from "@/lib/api";

function history(
  intervalReturn: number | null,
  reason?: string,
): WatchlistHistoryResponse {
  return {
    code: "TEST",
    symbol: "TEST",
    name: "Test",
    market: "us",
    currency: "USD",
    period: "1Y",
    adjustment: "adjusted",
    formula_version: "market-metrics-v1",
    bars: [
      { date: "2025-01-02", close: 100, volume: 1_000 },
      { date: "2026-01-02", close: 200, volume: null },
    ],
    baseline: { date: "2025-01-02", value: 100, source: "adjusted_history" },
    endpoint: { date: "2026-01-02", value: 200, source: "adjusted_history" },
    metrics: {
      interval_return_pct: intervalReturn,
      dca_return_pct: 8.5,
      dca_max_loss_pct: -4.2,
      dca_contribution_count: 252,
      buy_hold_max_loss_pct: -7.5,
      max_drawdown_pct: -12.0,
    },
    metric_reasons: reason ? { interval_return_pct: reason } : {},
    data_status: {
      quality: "warning",
      source: "fixture",
      data_through: "2026-01-02",
      issues: [{ code: "missing_volume", message: "成交量缺失", blocking: false }],
    },
  };
}

describe("PriceHistoryChart", () => {
  it("renders backend metrics without recomputing from plotted bars", () => {
    render(
      <PriceHistoryChart
        history={history(12.34)}
        period="1Y"
        onPeriodChange={() => undefined}
        showRisk
      />,
    );

    expect(screen.getByText("+12.34%")).toBeInTheDocument();
    expect(screen.getByText("-4.2%")).toBeInTheDocument();
    expect(screen.getByText("-7.5%")).toBeInTheDocument();
    expect(screen.getByText("-12.0%")).toBeInTheDocument();
    expect(screen.getByText("成交量缺失")).toBeInTheDocument();
  });

  it("shows unavailable instead of zero for a missing baseline", () => {
    render(
      <PriceHistoryChart
        history={history(null, "missing_baseline")}
        period="1Y"
        onPeriodChange={() => undefined}
      />,
    );

    expect(screen.getByText("数据不足")).toBeInTheDocument();
    expect(screen.queryByText("0.00%")).not.toBeInTheDocument();
  });
});
