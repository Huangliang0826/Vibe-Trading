import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ getAnalyticsDevelopment: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), api: apiMock }));
import { DevelopmentView } from "../DevelopmentView";

it("shows feature provenance and honest release comparison", async () => {
  apiMock.getAnalyticsDevelopment.mockResolvedValue({
    data_through: "2026-07-13", generated_at: "2026-07-13", sample_count: 2,
    calculation_version: "analytics.v1", warnings: [], days: 30,
    commits: [], module_churn: [], releases: [],
    feature_groups: [{ label: "模拟盘实验对比", commit_shas: ["466146f", "ea104ad"], subjects: [], modules: ["frontend/paper-trading"], started_at: "", ended_at: "", files_changed: 17, insertions: 620, deletions: 48 }],
    release_comparison: { status: "insufficient_sample", tag: "v0.1.9", window_days: 7, metrics: [], causal: false, disclaimer: "时间相关性，不代表该版本造成了指标变化。" },
  });
  render(<DevelopmentView days={30} />);
  expect(await screen.findByText("模拟盘实验对比")).toBeInTheDocument();
  expect(screen.getByText(/466146f/)).toBeInTheDocument();
  expect(screen.getByText(/ea104ad/)).toBeInTheDocument();
  expect(screen.getByText("17 files")).toBeInTheDocument();
  expect(screen.getByText("+620")).toBeInTheDocument();
  expect(screen.getByText("−48")).toBeInTheDocument();
  expect(screen.getByText("时间相关性，不代表该版本造成了指标变化。")).toBeInTheDocument();
  expect(screen.getByText("样本不足")).toBeInTheDocument();
});
