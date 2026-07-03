import { describe, expect, it } from "vitest";

import { Overview, shouldRenderHistoricalEvents, stockChartViewTabs } from "../Overview";


describe("Overview historical event tabs", () => {
  it("shows historical events for A shares, HK, and US", () => {
    expect(stockChartViewTabs("hk").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("us").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("cn").map((tab) => tab.key)).toContain("historical_events");
  });

  it("renders the historical event component for A shares", () => {
    expect(shouldRenderHistoricalEvents("historical_events", "cn")).toBe(true);
    expect(shouldRenderHistoricalEvents("historical_events", "hk")).toBe(true);
    expect(shouldRenderHistoricalEvents("historical_events", "us")).toBe(true);
  });
});

describe("Overview opportunity modules", () => {
  it("does not mount today's opportunities or opportunity quality", () => {
    const componentBody = Overview.toString();

    expect(componentBody).not.toContain("TodayOpportunities");
    expect(componentBody).not.toContain("OpportunityCalibration");
  });
});
