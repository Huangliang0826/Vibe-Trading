import { beforeEach, describe, expect, it } from "vitest";
import {
  historyCacheKey,
  quoteCacheKey,
  readOverviewCache,
  writeOverviewCache,
} from "../overview-price-cache";

describe("overview price cache", () => {
  beforeEach(() => localStorage.clear());

  it("isolates history by market, symbol, and period", () => {
    expect(historyCacheKey("cn", "600519", "1Y")).not.toBe(historyCacheKey("cn", "600519", "3Y"));
    expect(historyCacheKey("cn", "600519", "1Y")).not.toBe(historyCacheKey("hk", "600519", "1Y"));
    expect(quoteCacheKey("us", "aapl")).toBe(quoteCacheKey("us", "AAPL"));
  });

  it("distinguishes fresh and stale values without discarding stale data", () => {
    writeOverviewCache("history:cn:600519:1Y", { bars: [1] }, 1_000);

    expect(readOverviewCache("history:cn:600519:1Y", 24_000, 20_000)).toEqual({
      value: { bars: [1] }, isFresh: true,
    });
    expect(readOverviewCache("history:cn:600519:1Y", 24_000, 30_000)).toEqual({
      value: { bars: [1] }, isFresh: false,
    });
  });

  it("ignores malformed cache entries", () => {
    localStorage.setItem("vibe:overview-market-metrics-v1:broken", "not-json");
    expect(readOverviewCache("broken", 1_000)).toBeNull();
  });
});
