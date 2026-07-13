import { beforeEach, describe, expect, it } from "vitest";

import {
  compactStrategyResponse, forecastSessionKey, readSessionCache, strategySessionKey, writeSessionCache,
} from "../forecast-session-cache";

describe("forecast session cache", () => {
  beforeEach(() => sessionStorage.clear());

  it("restores unexpired values and rejects expired values", () => {
    writeSessionCache("forecast:test", { code: "NVDA" }, 1000);

    expect(readSessionCache("forecast:test", 2000, 1500)).toEqual({ code: "NVDA" });
    expect(readSessionCache("forecast:test", 2000, 4001)).toBeNull();
  });

  it("stores only chart-relevant strategy fields", () => {
    const compact = compactStrategyResponse({
      code: "600519", candidates: [{ strategy: { name: "grid" } }],
      best: { equity_curve: [{ time: "x", equity: 1 }], trades: [{ entry_date: "2025-01-01" }] },
      selection: { robust_result: { strategies: new Array(25).fill({}) }, selected_strategy: "grid" },
    });

    expect(compact.candidates).toEqual([{ strategy: { name: "grid" } }]);
    expect(compact.best.equity_curve).toEqual([]);
    expect(compact.best.trades).toHaveLength(1);
    expect(compact.selection.robust_result).toBeUndefined();
  });

  it("isolates forecast ranges and per-stock strategy caches", () => {
    expect(forecastSessionKey("cn", "600519", 1260, 1260)).toBe("forecast:cn:600519:1260:1260");
    expect(strategySessionKey("cn", "600519")).toBe("strategy:v2:cn:600519");
  });
});
