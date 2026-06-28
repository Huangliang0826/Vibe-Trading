import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const setOption = vi.fn();

vi.mock("@/lib/echarts", () => ({
  echarts: {
    init: () => ({
      setOption,
      resize: vi.fn(),
      dispose: vi.fn(),
    }),
  },
}));

import { MiniEquityChart } from "../MiniEquityChart";

describe("MiniEquityChart", () => {
  beforeEach(() => setOption.mockClear());

  it("draws exact segments without smoothing past observed equity", async () => {
    render(
      <MiniEquityChart
        data={[
          { time: "2026-01-01", equity: 100 },
          { time: "2026-01-02", equity: 70 },
          { time: "2026-01-03", equity: 110 },
        ]}
      />,
    );

    await waitFor(() => expect(setOption).toHaveBeenCalled());
    expect(setOption.mock.calls[0][0].series[0].smooth).toBe(false);
  });
});
