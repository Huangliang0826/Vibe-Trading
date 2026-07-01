import { describe, expect, it } from "vitest";

import { stockChartViewTabs } from "../Overview";


describe("Overview historical event tabs", () => {
  it("shows historical events for HK and US but not A shares", () => {
    expect(stockChartViewTabs("hk").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("us").map((tab) => tab.key)).toContain("historical_events");
    expect(stockChartViewTabs("cn").map((tab) => tab.key)).not.toContain("historical_events");
  });
});
