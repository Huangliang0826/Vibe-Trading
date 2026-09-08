import { describe, expect, it } from "vitest";

import { MIN_BARS_FOR_INDICATORS, describeTrend } from "../trend-narrative";

const bars = (closes: number[]) => closes.map((close) => ({ close }));
const ramp = (n: number, from: number, step: number) =>
  bars(Array.from({ length: n }, (_, i) => from + i * step));

describe("describeTrend", () => {
  it("says so when the window is too short to compute", () => {
    const text = describeTrend(ramp(MIN_BARS_FOR_INDICATORS - 1, 100, 1))[0];
    expect(text).toContain("数据点不足");
  });

  it("reads a sustained uptrend as bullish alignment", () => {
    const text = describeTrend(ramp(260, 100, 1)).join(" ");
    expect(text).toContain("多头排列");
    expect(text).toContain("位于 50 日均线之上");
  });

  it("reads a sustained downtrend as bearish alignment", () => {
    const text = describeTrend(ramp(260, 400, -1)).join(" ");
    expect(text).toContain("空头排列");
    expect(text).toContain("跌破 50 日均线");
  });

  it("notes when the long moving average has no room to compute", () => {
    const text = describeTrend(ramp(120, 100, 1)).join(" ");
    expect(text).toContain("不足 200 日");
    expect(text).not.toContain("排列");
  });

  it("covers MACD, moving averages and RSI", () => {
    const text = describeTrend(ramp(260, 100, 1)).join(" ");
    expect(text).toContain("MACD");
    expect(text).toContain("均线");
    expect(text).toContain("RSI(14)");
  });

  it("flags overbought on a relentless rise", () => {
    expect(describeTrend(ramp(260, 100, 1)).join(" ")).toContain("超买区");
  });

  it("always carries the descriptive, non-advisory caveat", () => {
    expect(describeTrend(ramp(260, 100, 1)).join(" ")).toContain("不构成交易建议");
  });

  it("ignores non-finite closes rather than throwing", () => {
    const dirty = [...ramp(260, 100, 1), { close: Number.NaN }];
    expect(() => describeTrend(dirty)).not.toThrow();
    expect(describeTrend(dirty).join(" ")).toContain("MACD");
  });
});
