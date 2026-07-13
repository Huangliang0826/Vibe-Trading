import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ getAnalyticsResearchQuality: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()), api: apiMock,
}));
vi.mock("@/components/analytics/TrendChart", () => ({ TrendChart: () => <div>trend</div> }));

import { ResearchQualityView } from "../ResearchQualityView";

const scannerFixture = {
  data_through: "2026-07-13", generated_at: "2026-07-13T12:00:00Z",
  sample_count: 40, calculation_version: "analytics.v1", warnings: [], days: 30,
  status: "available", value: 0.575,
  freshness: "fresh",
  coverage: { window_days: 30, covered_days: 1, coverage_rate: 1 / 30, sources: [] },
  series: [{ bucket: "2026-07-13", subject: "scanner", subject_id: "all", market: "us", horizon: "5d", regime: "all", metric: "hit_rate", value: 0.575, sample_count: 40, interval_low: 0.42, interval_high: 0.71, formula_version: "scanner.v1", reason: null }],
};

describe("ResearchQualityView", () => {
  beforeEach(() => {
    apiMock.getAnalyticsResearchQuality
      .mockResolvedValueOnce(scannerFixture)
      .mockResolvedValueOnce({ ...scannerFixture, status: "insufficient_sample", value: null, series: [{ ...scannerFixture.series[0], subject: "forecast", value: null, sample_count: 2, reason: "insufficient_sample" }] })
      .mockResolvedValueOnce({ ...scannerFixture, series: [{ ...scannerFixture.series[0], subject: "backtest", horizon: "run", metric: "sharpe", value: 1.2 }] });
  });

  it("shows uncertainty and never turns missing quality into zero", async () => {
    render(<ResearchQualityView days={30} />);
    expect(screen.getByRole("option", { name: "10d" })).toBeInTheDocument();
    expect(await screen.findByText("57.5%")).toBeInTheDocument();
    expect(screen.getByText("覆盖 1 / 30 天")).toBeInTheDocument();
    expect(screen.getByText("n=40")).toBeInTheDocument();
    expect(screen.getByText(/42.0%.*71.0%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Forecast" }));
    expect(await screen.findByText("样本不足")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Backtest" }));
    await waitFor(() => expect(apiMock.getAnalyticsResearchQuality).toHaveBeenLastCalledWith(
      expect.objectContaining({ subject: "backtest", horizon: "run", market: undefined }),
    ));
  });
});
