import { describe, expect, it } from "vitest";

import { computePaperEquityStats } from "../PaperEquityChart";
import type { EquityPoint } from "@/lib/api";

const data: EquityPoint[] = [
  { time: "2026-01-01", equity: 120, drawdown: 0 },
  { time: "2026-01-02", equity: 80, drawdown: -1 / 3 },
  { time: "2026-01-03", equity: 110, drawdown: -1 / 12 },
];

describe("computePaperEquityStats", () => {
  it("calculates return and maximum loss against starting capital", () => {
    const result = computePaperEquityStats(data, 100);

    expect(result?.totalReturn).toBeCloseTo(0.1);
    expect(result?.maxLoss).toBeCloseTo(-0.2);
    expect(result?.initial).toBe(100);
  });

  it("reports zero maximum loss when equity never falls below capital", () => {
    const result = computePaperEquityStats(
      [
        { time: "2026-01-01", equity: 105, drawdown: 0 },
        { time: "2026-01-02", equity: 110, drawdown: 0 },
      ],
      100,
    );

    expect(result?.maxLoss).toBe(0);
  });
});
