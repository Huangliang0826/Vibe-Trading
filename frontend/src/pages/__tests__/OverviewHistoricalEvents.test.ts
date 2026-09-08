import { describe, expect, it } from "vitest";

import {
  Overview, isFundLike, shouldRenderHistoricalEvents, stockChartViewTabs, supportsValuation,
} from "../Overview";

const keys = (market: "cn" | "hk" | "us", code = "") =>
  stockChartViewTabs(market, code).map((tab) => tab.key);

describe("stock chart view tabs", () => {
  it("drops the removed 资金面 / 事件 views entirely", () => {
    for (const m of ["cn", "hk", "us"] as const) {
      expect(keys(m, "300750")).not.toContain("capital");
      expect(keys(m, "300750")).not.toContain("events");
    }
  });

  it("hides 市值 and 重大历史事件 while keeping their implementations", () => {
    expect(keys("cn", "300750")).not.toContain("mktcap");
    expect(keys("cn", "300750")).not.toContain("historical_events");
    // The renderer is intentionally left intact so the view can be restored.
    expect(shouldRenderHistoricalEvents("historical_events", "cn")).toBe(true);
  });

  it("keeps PE/PB for ordinary A-share and HK stocks", () => {
    expect(keys("cn", "300750")).toEqual(["price", "pe", "pb"]);
    expect(keys("hk", "00700")).toEqual(["price", "pe", "pb"]);
  });

  it("drops PE/PB for ETFs", () => {
    expect(keys("cn", "159688")).toEqual(["price"]);   // 恒生互联网ETF
    expect(keys("hk", "2800")).toEqual(["price"]);     // 盈富基金
    expect(keys("hk", "03188")).toEqual(["price"]);    // 华夏沪深三百
  });

  it("drops PE/PB for every US symbol — the source carries no US valuation", () => {
    expect(keys("us", "AAPL")).toEqual(["price"]);
    expect(keys("us", "SPY")).toEqual(["price"]);
  });
});

describe("isFundLike", () => {
  it("recognises A-share ETF/LOF code ranges", () => {
    expect(isFundLike("cn", "159559")).toBe(true);   // 深 15xxxx
    expect(isFundLike("cn", "510300")).toBe(true);   // 沪 51xxxx
    expect(isFundLike("cn", "588000")).toBe(true);   // 沪 58xxxx
    expect(isFundLike("cn", "300750")).toBe(false);  // 创业板个股
    expect(isFundLike("cn", "688017")).toBe(false);  // 科创板个股
  });

  it("recognises HK ETF ranges and tolerates leading zeros", () => {
    expect(isFundLike("hk", "2800")).toBe(true);
    expect(isFundLike("hk", "03188")).toBe(true);
    expect(isFundLike("hk", "3032")).toBe(true);
    expect(isFundLike("hk", "00700")).toBe(false);
    expect(isFundLike("hk", "9988")).toBe(false);
  });

  it("is not used to classify US symbols", () => {
    expect(isFundLike("us", "SPY")).toBe(false);
    // US is excluded by supportsValuation instead, for lack of a data source.
    expect(supportsValuation("us", "SPY")).toBe(false);
    expect(supportsValuation("us", "AAPL")).toBe(false);
  });
});

describe("Overview opportunity modules", () => {
  it("does not mount today's opportunities or opportunity quality", () => {
    const componentBody = Overview.toString();

    expect(componentBody).not.toContain("TodayOpportunities");
    expect(componentBody).not.toContain("OpportunityCalibration");
  });
});
