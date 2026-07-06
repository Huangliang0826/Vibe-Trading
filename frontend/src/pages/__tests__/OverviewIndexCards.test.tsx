import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getMarketIndices: vi.fn(),
  getWatchlistCodes: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: apiMock };
});

import { Overview } from "../Overview";

describe("Overview index cards", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    apiMock.getWatchlistCodes.mockResolvedValue({ codes: [] });
    apiMock.getMarketIndices.mockResolvedValue([
      { code: "000001.SS", name: "上证指数", market: "A股", price: 3000, change_pct: 1, prev_close: 2970 },
      { code: "HSI", name: "恒生指数", market: "港股", price: 22000, change_pct: 1, prev_close: 21800 },
      { code: "^GSPC", name: "标普500", market: "美股", price: 6000, change_pct: 1, prev_close: 5940 },
    ]);
  });

  it("restores index cards immediately while refreshing in the background", () => {
    sessionStorage.setItem("overview-market-indices:v1", JSON.stringify({
      cachedAt: Date.now(),
      data: [
        { code: "sh000001", name: "缓存上证指数", market: "A股", price: 3000, change_pct: 1, prev_close: 2970 },
      ],
    }));
    apiMock.getMarketIndices.mockReturnValue(new Promise(() => {}));

    render(<Overview />);

    expect(screen.getByText("缓存上证指数")).toBeInTheDocument();
  });

  it("shows index points as integers without decimals", async () => {
    apiMock.getMarketIndices.mockResolvedValue([
      { code: "000001.SS", name: "上证指数", market: "A股", price: 3005.67, change_pct: 1.23, prev_close: 2970 },
      { code: "^GSPC", name: "标普500", market: "美股", price: 6123.49, change_pct: -0.5, prev_close: 6154 },
    ]);

    render(<Overview />);
    await waitFor(() => expect(screen.getByText("上证指数")).toBeInTheDocument());

    expect(screen.getByText("3,006")).toBeInTheDocument();
    expect(screen.getByText("6,123")).toBeInTheDocument();
    expect(screen.queryByText("3,005.67")).not.toBeInTheDocument();
    // 涨跌幅仍保留两位小数
    expect(screen.getByText("+1.23%")).toBeInTheDocument();
  });

  it("omits market labels and previous close values inside index cards", async () => {
    render(<Overview />);
    await waitFor(() => expect(screen.getByText("上证指数")).toBeInTheDocument());

    expect(screen.queryByText("A股")).not.toBeInTheDocument();
    expect(screen.queryByText("港股")).not.toBeInTheDocument();
    expect(screen.queryByText("美股")).not.toBeInTheDocument();
    expect(screen.queryByText(/昨收/)).not.toBeInTheDocument();

    expect(screen.getByText("A 股指数")).toBeInTheDocument();
    expect(screen.getByText("港股指数")).toBeInTheDocument();
    expect(screen.getByText("美股指数")).toBeInTheDocument();
  });
});
