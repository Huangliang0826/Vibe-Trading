import { describe, expect, it } from "vitest";

import { computeDailyDca } from "../PriceHistoryChart";
import type { PriceHistoryBar } from "@/lib/api";

function bars(closes: number[]): PriceHistoryBar[] {
  return closes.map((close, idx) => ({
    date: `2026-01-${String(idx + 1).padStart(2, "0")}`,
    open: close,
    high: close,
    low: close,
    close,
    volume: 1000,
  }));
}

describe("computeDailyDca", () => {
  it("reports maximum loss against contributed principal, not drawdown from NAV peak", () => {
    const result = computeDailyDca(bars([100, 50, 80]));

    expect(result?.totalReturn).toBeCloseTo(0.13333333333333353);
    expect(result?.maxLoss).toBeCloseTo(-0.25);
    expect(result?.contributions).toBe(3);
  });
});
