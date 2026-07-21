import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  listPaperTradingRuns: vi.fn().mockResolvedValue({ items: [] }),
  getWatchlistCodes: vi.fn().mockResolvedValue({ codes: [] }),
  getWatchlistQuote: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

vi.mock("@/components/paper-trading/AssetManagementTab", () => ({
  AssetManagementTab: () => <div>资产管理内容</div>,
}));

import { PaperTrading } from "../PaperTrading";

it("shows historical backtesting by default and opens asset management", async () => {
  const user = userEvent.setup();
  render(<PaperTrading />);

  expect(screen.getByText("自选快捷添加")).toBeInTheDocument();
  expect(screen.queryByText("资产管理内容")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "资产管理" }));
  expect(screen.getByText("资产管理内容")).toBeInTheDocument();
  expect(screen.queryByText("自选快捷添加")).not.toBeInTheDocument();
});
