import { beforeEach, describe, expect, it } from "vitest";
import {
  historyCacheKey,
  pruneOverviewCache,
  quoteCacheKey,
  readOverviewCache,
  writeOverviewCache,
} from "../overview-price-cache";

function overviewKeyCount() {
  let n = 0;
  for (let i = 0; i < localStorage.length; i++) {
    if (localStorage.key(i)?.startsWith("vibe:overview-price:")) n += 1;
  }
  return n;
}

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
    localStorage.setItem("vibe:overview-price:broken", "not-json");
    expect(readOverviewCache("broken", 1_000)).toBeNull();
  });

  it("prune keeps the newest entries and drops the oldest", () => {
    for (let i = 0; i < 10; i++) writeOverviewCache(`history:us:S${i}:1Y`, { bars: [i] }, 1_000 + i);
    expect(overviewKeyCount()).toBe(10);
    pruneOverviewCache(4);
    expect(overviewKeyCount()).toBe(4);
    // the 4 newest (highest savedAt) survive
    expect(readOverviewCache("history:us:S9:1Y", 1e12, 0)).not.toBeNull();
    expect(readOverviewCache("history:us:S0:1Y", 1e12, 0)).toBeNull();
  });

  it("evicts and retries when a write hits the quota", () => {
    const real = Storage.prototype.setItem;
    let failNext = true;
    // Fail only the first overview-price setItem to simulate a full quota,
    // then let the post-prune retry succeed.
    Storage.prototype.setItem = function (this: Storage, k: string, v: string) {
      if (failNext && k.startsWith("vibe:overview-price:")) {
        failNext = false;
        throw new DOMException("quota", "QuotaExceededError");
      }
      return real.call(this, k, v);
    };
    try {
      writeOverviewCache("history:us:S0:1Y", { bars: [0] }, 1_000); // seed something to prune
      writeOverviewCache("history:us:NEW:1Y", { bars: [1] }, 2_000); // first attempt throws, retry wins
      expect(readOverviewCache("history:us:NEW:1Y", 1e12, 0)).not.toBeNull();
    } finally {
      Storage.prototype.setItem = real;
    }
  });
});
