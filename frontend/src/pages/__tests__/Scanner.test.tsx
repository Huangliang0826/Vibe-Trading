import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getScanDates: vi.fn(),
  getScanByDate: vi.fn(),
  getScanLatest: vi.fn(),
  getScanTracking: vi.fn(),
  getScanCalibration: vi.fn(),
  runScan: vi.fn(),
}));

const marketMock = vi.hoisted(() => ({
  lastClosedTradingDay: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: apiMock,
}));

vi.mock("@/lib/market", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  lastClosedTradingDay: marketMock.lastClosedTradingDay,
}));

import { Scanner } from "../Scanner";

const oldScan = {
  universe: "sp500",
  asof: "2026-06-30",
  providers: ["factor_rank"],
  candidates: [
    { symbol: "AAPL", score: 80, provider_id: "factor_rank", attribution: "old", detail: {} },
  ],
  warnings: [],
};

const newScan = {
  ...oldScan,
  asof: "2026-07-01",
  candidates: [
    { symbol: "NVDA", score: 91, provider_id: "factor_rank", attribution: "new", detail: {} },
  ],
};

const hkScan = {
  ...oldScan,
  universe: "hstech",
  candidates: [
    { symbol: "700.HK", company_name: "腾讯控股", score: 88, provider_id: "factor_rank", attribution: "hk", detail: {} },
  ],
};

describe("Scanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    apiMock.getScanDates.mockResolvedValue({ dates: [oldScan.asof] });
    apiMock.getScanByDate.mockImplementation((_date, universe) =>
      Promise.resolve(universe === "hstech" ? hkScan : oldScan)
    );
    apiMock.getScanLatest.mockResolvedValue(oldScan);
    apiMock.getScanTracking.mockResolvedValue({ records: [] });
    apiMock.getScanCalibration.mockResolvedValue({ total_tracked: 0, filled: 0, alerts: [], ok: true });
    apiMock.runScan.mockResolvedValue(newScan);
    // 默认最新一期即最近已收盘交易日:不触发自动刷新
    marketMock.lastClosedTradingDay.mockReturnValue(oldScan.asof);
  });

  it("defaults to the HK market", async () => {
    render(<Scanner />);

    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(apiMock.getScanDates).toHaveBeenCalledWith("hstech");
    expect(apiMock.runScan).not.toHaveBeenCalled();
  });

  it("runs a fresh scan when the update button is clicked", async () => {
    render(<Scanner />);
    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));

    expect(apiMock.runScan).toHaveBeenCalledWith("hstech", 20);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    expect(screen.getByText("2026-07-01")).toBeInTheDocument();
  });

  it("can create the first scan manually when auto-refresh was already attempted", async () => {
    apiMock.getScanDates.mockResolvedValue({ dates: [] });
    localStorage.setItem("scan-auto-refresh:hstech", oldScan.asof);

    render(<Scanner />);
    expect(await screen.findByText("暂无扫描结果")).toBeInTheDocument();
    expect(apiMock.runScan).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));

    expect(apiMock.runScan).toHaveBeenCalledWith("hstech", 20);
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
  });

  it("only offers HK and US markets and can switch to US", async () => {
    render(<Scanner />);
    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "A股" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "美股" }));

    await waitFor(() => expect(apiMock.getScanDates).toHaveBeenLastCalledWith("sp500"));
    expect(apiMock.getScanByDate).toHaveBeenLastCalledWith(oldScan.asof, "sp500");
    expect(await screen.findByText("AAPL")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));
    expect(apiMock.runScan).toHaveBeenLastCalledWith("sp500", 20);
  });

  it("keeps forward-return columns visible while tracking data is unavailable", async () => {
    apiMock.getScanTracking.mockRejectedValue(new Error("no tracking"));

    render(<Scanner />);

    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "1日" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "5日" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "20日" })).toBeInTheDocument();
  });

  it("auto-runs today's scan on first open when the latest scan is stale", async () => {
    marketMock.lastClosedTradingDay.mockReturnValue("2026-07-03");
    let resolveRun: (value: unknown) => void = () => {};
    apiMock.runScan.mockImplementation(() => new Promise((resolve) => { resolveRun = resolve; }));

    render(<Scanner />);

    expect(await screen.findByText("正在生成今日扫描…")).toBeInTheDocument();
    expect(apiMock.runScan).toHaveBeenCalledWith("hstech", 20);
    expect(localStorage.getItem("scan-auto-refresh:hstech")).toBe("2026-07-03");

    resolveRun(newScan);
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
  });

  it("skips auto-run when it was already attempted for the same trading day", async () => {
    marketMock.lastClosedTradingDay.mockReturnValue("2026-07-03");
    localStorage.setItem("scan-auto-refresh:hstech", "2026-07-03");

    render(<Scanner />);

    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(apiMock.runScan).not.toHaveBeenCalled();
  });

  it("falls back to the latest saved scan silently when auto-run fails", async () => {
    marketMock.lastClosedTradingDay.mockReturnValue("2026-07-03");
    apiMock.runScan.mockRejectedValue(new Error("scan failed"));

    render(<Scanner />);

    expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
    expect(apiMock.runScan).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("暂无扫描结果")).not.toBeInTheDocument();
  });
});
