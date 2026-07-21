import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getWatchlistCodes: vi.fn(),
  getWatchlistQuote: vi.fn(),
  getLatestAssetManagementPlan: vi.fn(),
  calculateAssetManagementPlan: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

import { AssetManagementTab } from "../AssetManagementTab";

const plan = {
  plan_id: "asset-1",
  status: "feasible" as const,
  created_at: "2026-07-21T10:00:00Z",
  data_through: "2026-07-20",
  provider: "openrouter",
  model: "deepseek/deepseek-v4-pro",
  optimizer_version: "asset-allocation.v1",
  request: {
    candidates: [{ symbol: "1810", market: "hk" as const, name: "小米集团-W", asset_type: "stock" as const }],
    target_return: 0.075,
    max_drawdown: 0.20,
  },
  allocations: [
    { symbol: "1810", market: "hk" as const, name: "小米集团-W", asset_type: "stock" as const, weight: 0.10, range_min: 0.08, range_max: 0.12, risk_contribution: 1, expected_return: 0.08, reason: "主动增强仓。" },
    { symbol: "CASH", market: "cash" as const, name: "现金", asset_type: "cash" as const, weight: 0.90, range_min: 0.85, range_max: 0.95, risk_contribution: 0, expected_return: 0.015, reason: "控制回撤。" },
  ],
  metrics: { expected_return: 0.075, annual_volatility: 0.11, historical_max_drawdown: -0.18, stress_drawdown: -0.20, target_return: 0.075, max_drawdown_limit: 0.20 },
  summary: "满足目标的资产配置。",
  warnings: ["收益不代表未来表现。"],
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getWatchlistCodes.mockImplementation((market: string) => Promise.resolve({ codes: market === "hk" ? ["1810"] : [] }));
  apiMock.getWatchlistQuote.mockResolvedValue([{ code: "1810", name: "小米集团-W", market: "港股", price: 60, change_pct: 1, prev_close: 59 }]);
  apiMock.getLatestAssetManagementPlan.mockResolvedValue(null);
  apiMock.calculateAssetManagementPlan.mockResolvedValue(plan);
});

it("adds watchlist candidates, calculates, and renders the persisted plan shape", async () => {
  const user = userEvent.setup();
  render(<AssetManagementTab />);

  await user.click(await screen.findByRole("button", { name: /小米集团-W/ }));
  expect(screen.getByText("已选资产与目标")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "生成配置" }));

  await waitFor(() => expect(apiMock.calculateAssetManagementPlan).toHaveBeenCalledWith(expect.objectContaining({
    target_return: 0.075,
    max_drawdown: 0.20,
  })));
  expect(await screen.findByText("最新资产配置")).toBeInTheDocument();
  expect(screen.getByText("满足目标的资产配置。")).toBeInTheDocument();
  expect(screen.getByText("openrouter/deepseek/deepseek-v4-pro", { exact: false })).toBeInTheDocument();
});

it("restores the latest successful plan on mount", async () => {
  apiMock.getLatestAssetManagementPlan.mockResolvedValue(plan);
  render(<AssetManagementTab />);
  expect(await screen.findByText("最新资产配置")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新计算" })).toBeInTheDocument();
});

it("confirms a recalculation even when deterministic weights stay unchanged", async () => {
  const user = userEvent.setup();
  apiMock.getLatestAssetManagementPlan.mockResolvedValue(plan);
  apiMock.calculateAssetManagementPlan.mockResolvedValue({
    ...plan,
    plan_id: "asset-2",
    created_at: "2026-07-21T11:51:44Z",
  });
  render(<AssetManagementTab />);

  await user.click(await screen.findByRole("button", { name: "重新计算" }));

  expect(await screen.findByRole("status")).toHaveTextContent("重新计算完成");
  expect(screen.getByRole("status")).toHaveTextContent("建议比例保持不变");
  expect(apiMock.calculateAssetManagementPlan).toHaveBeenCalledTimes(1);
});
