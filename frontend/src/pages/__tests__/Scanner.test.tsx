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

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: apiMock,
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

const cnScan = {
  ...oldScan,
  universe: "csi300",
  candidates: [
    { symbol: "600519.SH", score: 88, provider_id: "factor_rank", attribution: "cn", detail: {} },
  ],
};

describe("Scanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getScanDates.mockResolvedValue({ dates: [oldScan.asof] });
    apiMock.getScanByDate.mockImplementation((_date, universe) =>
      Promise.resolve(universe === "csi300" ? cnScan : oldScan)
    );
    apiMock.getScanLatest.mockResolvedValue(oldScan);
    apiMock.getScanTracking.mockResolvedValue({ records: [] });
    apiMock.getScanCalibration.mockResolvedValue({ total_tracked: 0, filled: 0, alerts: [], ok: true });
    apiMock.runScan.mockResolvedValue(newScan);
  });

  it("runs a fresh scan when the update button is clicked", async () => {
    render(<Scanner />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));

    expect(apiMock.runScan).toHaveBeenCalledWith("sp500", 20);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    expect(screen.getByText("2026-07-01")).toBeInTheDocument();
  });

  it("can create the first scan from the empty state", async () => {
    apiMock.getScanDates.mockResolvedValue({ dates: [] });

    render(<Scanner />);
    expect(await screen.findByText("暂无扫描结果")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));

    expect(apiMock.runScan).toHaveBeenCalledWith("sp500", 20);
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
  });

  it("loads and refreshes the selected A-share universe", async () => {
    render(<Scanner />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "A股" }));

    await waitFor(() => expect(apiMock.getScanDates).toHaveBeenLastCalledWith("csi300"));
    expect(apiMock.getScanByDate).toHaveBeenLastCalledWith(oldScan.asof, "csi300");
    expect(await screen.findByText("600519.SH")).toBeInTheDocument();

    apiMock.runScan.mockResolvedValue(cnScan);
    await userEvent.click(screen.getByRole("button", { name: "更新机会" }));
    expect(apiMock.runScan).toHaveBeenLastCalledWith("csi300", 20);
  });
});
