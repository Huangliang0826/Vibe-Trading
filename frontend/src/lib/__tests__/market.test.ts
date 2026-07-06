import { describe, expect, it } from "vitest";

import { lastClosedTradingDay } from "../market";

describe("lastClosedTradingDay", () => {
  // 2026-07-06 is a Monday, 2026-07-03 the preceding Friday

  it("returns the previous trading day before HK close", () => {
    // Monday 09:00 HKT — HK market not yet closed
    expect(lastClosedTradingDay("hstech", new Date("2026-07-06T09:00:00+08:00"))).toBe("2026-07-03");
  });

  it("returns today after HK close plus buffer", () => {
    // Monday 17:00 HKT — past 16:30 buffer
    expect(lastClosedTradingDay("hstech", new Date("2026-07-06T17:00:00+08:00"))).toBe("2026-07-06");
  });

  it("stays on today between close and buffer end", () => {
    // Monday 16:15 HKT — closed but within the data-lag buffer
    expect(lastClosedTradingDay("hstech", new Date("2026-07-06T16:15:00+08:00"))).toBe("2026-07-03");
  });

  it("skips the weekend", () => {
    // Saturday 12:00 HKT
    expect(lastClosedTradingDay("hstech", new Date("2026-07-04T12:00:00+08:00"))).toBe("2026-07-03");
    // Sunday 20:00 HKT
    expect(lastClosedTradingDay("hstech", new Date("2026-07-05T20:00:00+08:00"))).toBe("2026-07-03");
  });

  it("uses New York time for the US market", () => {
    // Monday 08:00 HKT = Sunday 20:00 ET — US latest close is Friday
    expect(lastClosedTradingDay("sp500", new Date("2026-07-06T08:00:00+08:00"))).toBe("2026-07-03");
    // Monday 17:00 ET — past US close buffer
    expect(lastClosedTradingDay("sp500", new Date("2026-07-06T17:00:00-04:00"))).toBe("2026-07-06");
    // Monday 09:30 ET — before US close
    expect(lastClosedTradingDay("sp500", new Date("2026-07-06T09:30:00-04:00"))).toBe("2026-07-03");
  });
});
