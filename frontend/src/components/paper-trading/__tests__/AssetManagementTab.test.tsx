import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getWatchlistCodes: vi.fn(),
  getWatchlistQuote: vi.fn(),
  getLatestAssetTracking: vi.fn(),
  backtestAssetPortfolio: vi.fn(),
  startAssetTracking: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

import { AssetManagementTab } from "../AssetManagementTab";

const STORAGE_KEY = "asset-management-manual-portfolio-v1";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  apiMock.getWatchlistCodes.mockImplementation((market: string) => Promise.resolve({ codes: market === "hk" ? ["1810"] : [] }));
  apiMock.getWatchlistQuote.mockResolvedValue([{ code: "1810", name: "小米集团-W", market: "港股", price: 60, change_pct: 1, prev_close: 59 }]);
  apiMock.getLatestAssetTracking.mockResolvedValue(null);
  apiMock.backtestAssetPortfolio.mockResolvedValue({
    start_date: "2021-07-21", end_date: "2026-07-20", initial_capital: 100_000,
    final_value: 120_000, total_profit: 20_000, total_return: 0.2, cagr: 0.037,
    annual_average_return: 0.04, max_drawdown: -0.12, annual_volatility: 0.15,
    installments: 10, investment_completed_date: "2021-09-23", rebalances: 19,
    rebalance_dates: ["2021-12-23"], annual_returns: [], curve: [], warnings: [],
  });
  apiMock.startAssetTracking.mockResolvedValue({
    tracker_id: "portfolio-1", status: "building", created_at: "2026-07-21T10:00:00Z",
    initial_capital: 100_000, current_value: 100_000, cumulative_return: 0, today_return: 0,
    completed_installments: 1, total_installments: 10, next_installment_date: "2026-07-28",
    investment_completed_date: null, completed_rebalances: 0,
    last_rebalance_date: null, next_rebalance_date: null,
    strategic_cash: 75_000, deployment_cash: 22_500, positions: [], curve: [],
    last_updated: "2026-07-21T10:00:00Z", warnings: [],
  });
});

it("adds an asset and exposes only manual allocation controls", async () => {
  const user = userEvent.setup();
  render(<AssetManagementTab />);

  await user.click(await screen.findByRole("button", { name: /小米集团-W/ }));

  expect(screen.getByText("手动配置资产比例")).toBeInTheDocument();
  expect(screen.getByLabelText("1810 目标比例")).toBeInTheDocument();
  expect(screen.getByLabelText("现金目标比例")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成配置" })).not.toBeInTheDocument();
  expect(screen.queryByText("预期年化收益")).not.toBeInTheDocument();
  expect(screen.queryByText("最大可接受回撤")).not.toBeInTheDocument();
});

it("restores the saved manual portfolio without calling an optimizer", async () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    selected: [{ symbol: "1810", market: "hk", name: "小米集团-W", asset_type: "stock" }],
    weights: { "hk:1810": 25 },
    cashWeight: 75,
  }));

  render(<AssetManagementTab />);

  expect(await screen.findByLabelText("1810 目标比例")).toHaveValue(25);
  expect(screen.getByLabelText("现金目标比例")).toHaveValue(75);
  expect(screen.getByText("合计 100.0%")).toBeInTheDocument();
});

it("uses the manually confirmed weights for backtest and tracking", async () => {
  const user = userEvent.setup();
  render(<AssetManagementTab />);
  await user.click(await screen.findByRole("button", { name: /小米集团-W/ }));

  await user.clear(screen.getByLabelText("1810 目标比例"));
  await user.type(screen.getByLabelText("1810 目标比例"), "25");
  await user.clear(screen.getByLabelText("现金目标比例"));
  await user.type(screen.getByLabelText("现金目标比例"), "75");
  await user.click(screen.getByRole("button", { name: "一键回测" }));

  await waitFor(() => expect(apiMock.backtestAssetPortfolio).toHaveBeenCalledWith(expect.objectContaining({
    initial_capital: 100_000, installments: 10, interval_days: 7, years: 5, rebalance_months: 3,
    allocations: expect.arrayContaining([
      expect.objectContaining({ symbol: "1810", weight: 0.25 }),
      expect.objectContaining({ symbol: "CASH", weight: 0.75 }),
    ]),
  })));

  await user.click(screen.getByRole("button", { name: "开始追踪" }));
  await waitFor(() => expect(apiMock.startAssetTracking).toHaveBeenCalledWith(expect.objectContaining({
    initial_capital: 100_000, installments: 10, interval_days: 7,
  })));
});
