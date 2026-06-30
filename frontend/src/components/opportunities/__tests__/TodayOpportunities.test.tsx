import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getOpportunities: vi.fn(), getOpportunityDetail: vi.fn(), getOpportunityHistory: vi.fn(),
  refreshOpportunities: vi.fn(), getOpportunityRefreshJob: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), api: apiMock }));
vi.mock("@/lib/echarts", () => ({ echarts: { init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }) } }));

import { TodayOpportunities } from "../TodayOpportunities";

const item = {
  market: "hk" as const, code: "0700", company_name: "腾讯控股", snapshot_date: "2026-06-29",
  score: 82, score_change: 4, level: "优先关注" as const, latest_action: "entry" as const,
  signal_date: "2026-06-29", strategy_name: "donchian_breakout", strategy_label: "唐奇安突破",
  primary_reason: "策略信号提供主要正贡献", risk_reasons: [],
  dimensions: { strategy: 88, trend: 80, risk: 72, news: 60, valuation: null },
  data_as_of: "2026-06-29", stale: false, degraded: true, missing_dimensions: ["valuation"],
  score_version: "opportunity-v1", strategy_version: "oos-holdout-v1",
};

describe("TodayOpportunities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getOpportunities.mockResolvedValue({ items: [item], latest_success_at: "2026-06-29", active_job: null, last_refresh_error: null });
    apiMock.getOpportunityDetail.mockResolvedValue({ ...item, news: [], explanations: [], history_available: true });
    apiMock.getOpportunityHistory.mockResolvedValue([item]);
    apiMock.refreshOpportunities.mockResolvedValue({ job_id: "j1", status: "queued", markets: ["hk", "us"], trigger: "manual", completed: 0, total: 1, created_at: null, started_at: null, finished_at: null, updated_at: null, error: null });
    apiMock.getOpportunityRefreshJob.mockResolvedValue({ job_id: "j1", status: "completed", markets: ["hk", "us"], trigger: "manual", completed: 1, total: 1, created_at: null, started_at: null, finished_at: null, updated_at: null, error: null });
  });

  it("renders action-first row and forecast link", async () => {
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /腾讯控股/ })).toHaveAttribute("href", "/forecast#forecast-card-hk-0700");
    expect(screen.getByText("部分数据降级")).toBeInTheDocument();
  });

  it("shows only the top three until the remaining results are expanded", async () => {
    const rankedItems = [
      item,
      { ...item, code: "9988", company_name: "阿里巴巴-W", score: 76 },
      { ...item, market: "us" as const, code: "NVDA", company_name: "NVIDIA", score: 70 },
      { ...item, market: "us" as const, code: "AAPL", company_name: "Apple", score: 65 },
    ];
    apiMock.getOpportunities.mockResolvedValue({
      items: rankedItems, latest_success_at: "2026-06-29", active_job: null, last_refresh_error: null,
    });

    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);

    expect(await screen.findByText("NVIDIA")).toBeInTheDocument();
    expect(screen.queryByText("Apple")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "查看其余 1 只" }));
    expect(screen.getByText("Apple")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "收起机会列表" }));
    expect(screen.queryByText("Apple")).not.toBeInTheDocument();
  });

  it("does not show a list toggle when there are no hidden results", async () => {
    apiMock.getOpportunities.mockResolvedValue({
      items: [item, { ...item, code: "9988", company_name: "阿里巴巴-W" }],
      latest_success_at: "2026-06-29", active_job: null, last_refresh_error: null,
    });

    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);

    expect(await screen.findByText("阿里巴巴-W")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /查看其余/ })).not.toBeInTheDocument();
  });

  it("collapses back to the top three when filters change", async () => {
    const rankedItems = [
      item,
      { ...item, code: "9988", company_name: "阿里巴巴-W", score: 76 },
      { ...item, code: "3690", company_name: "美团-W", score: 70 },
      { ...item, code: "1810", company_name: "小米集团-W", score: 65 },
    ];
    apiMock.getOpportunities.mockResolvedValue({
      items: rankedItems, latest_success_at: "2026-06-29", active_job: null, last_refresh_error: null,
    });
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    await screen.findByText("美团-W");
    await userEvent.click(screen.getByRole("button", { name: "查看其余 1 只" }));
    expect(screen.getByText("小米集团-W")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "港股" }));

    await waitFor(() => expect(apiMock.getOpportunities).toHaveBeenLastCalledWith(expect.objectContaining({ market: "hk" })));
    expect(screen.queryByText("小米集团-W")).not.toBeInTheDocument();
  });

  it("polls refresh and reloads after completion", async () => {
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    await screen.findByText("腾讯控股");
    await userEvent.click(screen.getByRole("button", { name: "刷新机会" }));
    expect(apiMock.refreshOpportunities).toHaveBeenCalledWith(["hk", "us"], false);
    await waitFor(() => expect(apiMock.getOpportunities).toHaveBeenCalledTimes(2));
  });

  it("filters and expands details with history", async () => {
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    await screen.findByText("腾讯控股");
    await userEvent.click(screen.getByRole("button", { name: "港股" }));
    await waitFor(() => expect(apiMock.getOpportunities).toHaveBeenLastCalledWith(expect.objectContaining({ market: "hk" })));
    await userEvent.click(screen.getByRole("button", { name: "展开腾讯控股机会详情" }));
    await waitFor(() => expect(apiMock.getOpportunityHistory).toHaveBeenCalledWith("hk", "0700", 30));
    expect(await screen.findByText("缺失维度：valuation")).toBeInTheDocument();
  });

  it("shows readable API failure", async () => {
    apiMock.getOpportunities.mockRejectedValue(new Error("后端暂不可用"));
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    expect(await screen.findByText("后端暂不可用")).toBeInTheDocument();
  });

  it("shows stale data-insufficient state", async () => {
    apiMock.getOpportunities.mockResolvedValue({
      items: [{ ...item, score: null, level: "数据不足", stale: true, degraded: true }],
      latest_success_at: "2026-06-28", active_job: null, last_refresh_error: null,
    });
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    expect(await screen.findByText("数据不足")).toBeInTheDocument();
    expect(screen.getByText("数据已过期")).toBeInTheDocument();
  });

  it("resumes polling an active job loaded with the page", async () => {
    apiMock.getOpportunityRefreshJob.mockImplementation(() => new Promise(() => {}));
    apiMock.getOpportunities.mockResolvedValueOnce({
      items: [item], latest_success_at: "2026-06-29",
      active_job: { job_id: "j1", status: "running", markets: ["hk"], trigger: "manual", completed: 1, total: 3, created_at: null, started_at: null, finished_at: null, updated_at: null, error: null },
      last_refresh_error: null,
    }).mockResolvedValue({ items: [item], latest_success_at: "2026-06-29", active_job: null, last_refresh_error: null });
    render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
    expect(await screen.findByText("刷新进度 1/3")).toBeInTheDocument();
    await waitFor(() => expect(apiMock.getOpportunityRefreshJob).toHaveBeenCalledWith("j1"));
  });
});
