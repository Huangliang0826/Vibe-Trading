import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  listPaperTradingRuns: vi.fn().mockResolvedValue({ items: [] }),
  getWatchlistCodes: vi.fn().mockResolvedValue({ codes: [] }),
  getWatchlistQuote: vi.fn(),
  getWatchlistHistory: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()), api: apiMock,
}));
vi.mock("@/components/paper-trading/StrategyComparisonTab", () => ({
  StrategyComparisonTab: () => <div>统一策略比较内容</div>,
}));

import { PaperTrading } from "../PaperTrading";

it("keeps the existing backtest as the first and default tab", async () => {
  render(<PaperTrading />);
  const tabs = screen.getAllByRole("button")
    .map((button) => button.textContent)
    .filter((name) => ["历史回测", "策略比较"].includes(name || ""));
  expect(tabs).toEqual(["历史回测", "策略比较"]);
  expect(screen.getByText("投资组合")).toBeInTheDocument();
  expect(screen.queryByText("统一策略比较内容")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "策略比较" }));

  expect(screen.getByText("统一策略比较内容")).toBeInTheDocument();
});
