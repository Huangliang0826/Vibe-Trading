import { describe, expect, it } from "vitest";

import { Overview, stockChartViewTabs } from "../Overview";


describe("Overview historical event tabs", () => {
  it("shows historical events for A shares, HK, and US", () => {
    expect(stockChartViewTabs("hk").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("us").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("cn").map((tab) => tab.key)).toContain("historical_events");
  });
});

describe("Overview opportunity modules", () => {
  it("does not mount today's opportunities or opportunity quality", () => {
    const componentBody = Overview.toString();

    expect(componentBody).not.toContain("TodayOpportunities");
    expect(componentBody).not.toContain("OpportunityCalibration");
  });
});
