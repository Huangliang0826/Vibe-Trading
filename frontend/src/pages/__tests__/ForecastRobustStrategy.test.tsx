import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getForecast: vi.fn(),
  getForecastBestPaperStrategy: vi.fn(),
}));

vi.mock("@/lib/api", async (original) => ({ ...(await original<object>()), api: apiMock }));
vi.mock("@/components/charts/ForecastChart", () => ({ ForecastChart: () => <div>chart</div> }));

import { Forecast, formatHistoryDuration } from "../Forecast";

const robustPayload = {
  code: "NVDA", name: "NVIDIA", market: "us", reliable: true,
  start_date: "2006-07-03", end_date: "2026-07-01", signal_as_of: "2026-07-02",
  selection_cached: true, signal_cached: true,
  selection: {
    selected_strategy: "donchian_breakout", selected_at: "2026-07-02T08:00:00Z",
    valid_until: "2027-07-02T08:00:00Z", reliable: true,
  },
  oos_validation: {
    start_date: "2025-07-02", end_date: "2026-07-01", passed: true,
    metrics: { total_return: 0.18, sharpe: 0.9, max_drawdown: -0.12 },
  },
  best: {
    strategy: { name: "donchian_breakout", label: "唐奇安突破" },
    metrics: { total_return: 0.5, max_drawdown: -0.2, sharpe: 1.1 }, trades: [],
  },
  candidates: [], summary: "稳健策略说明",
};

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("watchlist-us", JSON.stringify(["NVDA"]));
  apiMock.getForecast.mockResolvedValue({ code: "NVDA", name: "NVIDIA", model: true });
  apiMock.getForecastBestPaperStrategy.mockResolvedValue(robustPayload);
});

it("labels the annual robust selection and daily signal cache", async () => {
  render(<Forecast />);

  expect(await screen.findByText("最稳健：唐奇安突破")).toBeInTheDocument();
  expect(screen.getByText("总收益 +50.0%（20年）")).toBeInTheDocument();
  expect(screen.getByText(/样本外收益 \+18.0%/)).toBeInTheDocument();
  expect(screen.getByText(/年度选择已缓存/)).toBeInTheDocument();
  expect(screen.getByText(/每日信号已缓存/)).toBeInTheDocument();
  expect(screen.getByText(/有效至 2027-07-02/)).toBeInTheDocument();
});

it("formats short histories in months", () => {
  expect(formatHistoryDuration("2025-11-01", "2026-07-01")).toBe("8个月");
});

it("marks adaptive short-history selection as low confidence", async () => {
  apiMock.getForecastBestPaperStrategy.mockResolvedValue({
    ...robustPayload,
    selection: {
      ...robustPayload.selection,
      confidence_level: "low",
      history_note: "历史不足4年，使用1年滚动窗口和6个月样本外验证",
    },
  });

  render(<Forecast />);

  expect(await screen.findByText(/低可信度 · 历史不足4年/)).toBeInTheDocument();
});
