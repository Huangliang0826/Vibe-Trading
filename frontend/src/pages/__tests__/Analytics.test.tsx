import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getAnalyticsUsage: vi.fn(),
  getAnalyticsSystemHealth: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: apiMock,
}));

vi.mock("@/components/analytics/TrendChart", () => ({
  TrendChart: ({ title }: { title: string }) => <div>{title}</div>,
}));

import { Analytics } from "../Analytics";

const base = {
  data_through: "2026-07-13",
  generated_at: "2026-07-13T12:00:00Z",
  sample_count: 42,
  calculation_version: "analytics.v1",
  warnings: [],
  days: 30,
  freshness: "fresh",
  coverage: { window_days: 30, covered_days: 1, coverage_rate: 1 / 30, sources: [] },
};

describe("Analytics", () => {
  beforeEach(() => {
    apiMock.getAnalyticsUsage.mockResolvedValue({
      ...base,
      points: [{ bucket: "2026-07-13", metric: "effective_research_sessions", dimensions: {}, value: 8, sample_count: 8 }],
      funnel: [],
    });
    apiMock.getAnalyticsSystemHealth.mockResolvedValue({
      ...base,
      points: [{ bucket: "2026-07-13", metric: "duration_p95_ms", dimensions: {}, value: 320, sample_count: 12 }],
    });
  });

  it("renders usage trends and switches to system health", async () => {
    render(<Analytics />);
    expect(await screen.findByText("有效研究会话")).toBeInTheDocument();
    expect(screen.getByText("覆盖 1 / 30 天")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "系统健康" }));
    expect(await screen.findByText("P95 延迟")).toBeInTheDocument();
  });
});
