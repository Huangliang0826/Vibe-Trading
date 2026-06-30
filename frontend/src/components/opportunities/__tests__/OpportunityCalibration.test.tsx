import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ getOpportunityCalibration: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), api: apiMock }));

import { OpportunityCalibration } from "../OpportunityCalibration";

const summary = {
  scope: "top3" as const,
  calculated_at: "2026-06-30T12:00:00Z",
  periods: [5, 20, 60].map((horizon) => ({
    horizon_days: horizon as 5 | 20 | 60,
    completed_samples: 12,
    pending_samples: 3,
    missing_samples: 1,
    win_rate: 0.625,
    outperformance_rate: 0.583,
    average_return: 0.042,
    average_excess_return: 0.018,
    max_loss: -0.12,
  })),
};

describe("OpportunityCalibration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getOpportunityCalibration.mockResolvedValue(summary);
  });

  it("loads top-three quality metrics only after expanding", async () => {
    render(<OpportunityCalibration />);
    expect(screen.getByText("机会质量")).toBeInTheDocument();
    expect(apiMock.getOpportunityCalibration).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "展开机会质量" }));

    await waitFor(() => expect(apiMock.getOpportunityCalibration).toHaveBeenCalledWith("top3"));
    expect(screen.getByText("5 日")).toBeInTheDocument();
    expect(screen.getAllByText("12 个样本")).toHaveLength(3);
    expect(screen.getAllByText("62.5%")).toHaveLength(3);
    expect(screen.getAllByText("-12.0%")).toHaveLength(3);
  });

  it("reloads metrics when switching to all opportunities", async () => {
    render(<OpportunityCalibration />);
    await userEvent.click(screen.getByRole("button", { name: "展开机会质量" }));
    await screen.findByText("5 日");
    await userEvent.click(screen.getByRole("button", { name: "全部机会" }));
    await waitFor(() => expect(apiMock.getOpportunityCalibration).toHaveBeenLastCalledWith("all"));
  });

  it("shows an accumulation state when no horizon has matured", async () => {
    apiMock.getOpportunityCalibration.mockResolvedValue({
      ...summary,
      periods: summary.periods.map((period) => ({
        ...period, completed_samples: 0, win_rate: null, outperformance_rate: null,
        average_return: null, average_excess_return: null, max_loss: null,
      })),
    });
    render(<OpportunityCalibration />);
    await userEvent.click(screen.getByRole("button", { name: "展开机会质量" }));
    expect((await screen.findAllByText("样本积累中"))).toHaveLength(3);
  });
});
