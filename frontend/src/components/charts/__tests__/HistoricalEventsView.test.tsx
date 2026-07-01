import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  startHistoricalEventRun: vi.fn(), getHistoricalEventRun: vi.fn(), getHistoricalEvents: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), api: apiMock }));
vi.mock("@/lib/echarts", () => ({
  echarts: { init: () => ({ setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() }) },
}));

import { HistoricalEventsView } from "../HistoricalEventsView";

const bars = [
  { date: "2024-05-13", open: 100, high: 100, low: 100, close: 100, volume: 1 },
  { date: "2024-05-16", open: 118.6, high: 118.6, low: 118.6, close: 118.6, volume: 1 },
];
const event = {
  event_id: "hk-0700-2024-05-14-2024-05-16", market: "hk" as const, symbol: "0700",
  company_name: "腾讯控股", start_date: "2024-05-14", end_date: "2024-05-16",
  direction: "up" as const, return_pct: 18.6, trigger_windows: [3], volatility_filter_available: true,
  benchmark_symbol: "^HSI", benchmark_return_pct: 1.2, relative_return_pct: 17.4,
  market_context: "个股事件驱动", driver_type: "财报", primary_driver: "季度业绩高于预期",
  narrative: "收入及净利润高于市场预期。", confidence: "高" as const,
  evidence: [{ title: "腾讯公布第一季度业绩", url: "https://example.com/results", snippet: "", source: "港交所", published_at: "2024-05-14", evidence_type: "财报" }],
  alternative_factors: [], causality_note: "相关性不等于因果关系。",
  detector_version: "major-move-v1", analysis_version: "historical-event-analysis-v1", analyzed_at: "2026-07-01T00:00:00Z",
};

describe("HistoricalEventsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.startHistoricalEventRun.mockResolvedValue({ run_id: "r1", status: "completed", cached: true, event_count: 1 });
    apiMock.getHistoricalEvents.mockResolvedValue([event]);
  });

  it("starts lazily when mounted and displays cached event counts", async () => {
    render(<HistoricalEventsView market="hk" code="0700" companyName="腾讯控股" period="1Y" bars={bars} onPeriodChange={vi.fn()} />);

    await waitFor(() => expect(apiMock.startHistoricalEventRun).toHaveBeenCalledWith("hk", "0700", "腾讯控股", "1Y", false));
    expect(await screen.findByText("1 次重大波动")).toBeInTheDocument();
    expect(screen.getByText("1 次大涨")).toBeInTheDocument();
    expect(screen.getByText("本地缓存")).toBeInTheDocument();
  });

  it("opens an immediate summary and traceable evidence", async () => {
    render(<HistoricalEventsView market="hk" code="0700" companyName="腾讯控股" period="1Y" bars={bars} onPeriodChange={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: "打开2024-05-14重大事件" }));

    expect(screen.getByRole("button", { name: "关闭事件摘要" })).toBeInTheDocument();
    expect(screen.getAllByText("季度业绩高于预期")).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "腾讯公布第一季度业绩" })[0]).toHaveAttribute("href", "https://example.com/results");
  });
});
