import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataCoverageSummary } from "../DataCoverageSummary";

describe("DataCoverageSummary", () => {
  it("explains partial coverage without showing a fake zero", () => {
    render(
      <DataCoverageSummary
        freshness="stale"
        coverage={{
          window_days: 30,
          covered_days: 7,
          coverage_rate: 7 / 30,
          sources: [
            {
              source: "forecast",
              status: "source_unavailable",
              last_attempted_at: "2026-07-13T10:00:00Z",
              last_success_at: null,
              data_through: null,
              records_scanned: 0,
              events_written: 0,
              coverage_days: 0,
              reason: "no_persisted_forecast_history",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("覆盖 7 / 30 天")).toBeInTheDocument();
    expect(
      screen.getByText("暂无可回填的 Forecast 历史；新结果将从现在开始积累。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0% 准确率")).not.toBeInTheDocument();
  });
});
