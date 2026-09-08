import { describe, expect, it } from "vitest";

import {
  INDICATOR_CAVEAT, MIN_BARS_FOR_INDICATORS, indicatorRows, indicatorSnapshot,
} from "../trend-narrative";

const ohlc = (n: number, from: number, step: number) =>
  Array.from({ length: n }, (_, i) => {
    const close = from + i * step;
    return { close, high: close + 2, low: close - 2 };
  });
const closeOnly = (n: number, from: number, step: number) =>
  Array.from({ length: n }, (_, i) => ({ close: from + i * step }));

const byName = (rows: ReturnType<typeof indicatorRows>, prefix: string) =>
  rows.find((r) => r.name.startsWith(prefix));

describe("indicatorRows", () => {
  it("is empty below the minimum bar count", () => {
    expect(indicatorRows(ohlc(MIN_BARS_FOR_INDICATORS - 1, 100, 1))).toEqual([]);
  });

  it("covers every indicator as its own row", () => {
    const names = indicatorRows(ohlc(260, 100, 1)).map((r) => r.name);
    expect(names.some((n) => n.startsWith("MACD"))).toBe(true);
    expect(names.some((n) => n.startsWith("均线"))).toBe(true);
    expect(names.some((n) => n.startsWith("RSI"))).toBe(true);
    expect(names.some((n) => n.startsWith("BOLL"))).toBe(true);
    expect(names.some((n) => n.startsWith("ATR"))).toBe(true);
  });

  it("marks an uptrend bullish and a downtrend bearish", () => {
    const up = byName(indicatorRows(ohlc(260, 100, 1)), "均线")!;
    expect(up.reading).toContain("多头排列");
    expect(up.tone).toBe("up");

    const down = byName(indicatorRows(ohlc(260, 400, -1)), "均线")!;
    expect(down.reading).toContain("空头排列");
    expect(down.tone).toBe("down");
  });

  it("notes when the 200-day average has no room to compute", () => {
    const row = byName(indicatorRows(ohlc(120, 100, 1)), "均线")!;
    expect(row.value).toContain("—");
    expect(row.reading).toContain("不足 200 日");
  });

  it("flags RSI extremes with the matching tone", () => {
    const overbought = byName(indicatorRows(ohlc(260, 100, 1)), "RSI")!;
    expect(overbought.reading).toBe("超买区");
    expect(overbought.tone).toBe("down");
  });

  it("reports ATR as value and share of price", () => {
    const row = byName(indicatorRows(ohlc(260, 100, 1)), "ATR")!;
    expect(row.value).toMatch(/\d+\.\d{2}\(\d+\.\d{2}%\)/);
  });

  it("says ATR is uncomputable without high/low instead of faking it", () => {
    const row = byName(indicatorRows(closeOnly(260, 100, 1)), "ATR")!;
    expect(row.value).toBe("—");
    expect(row.reading).toContain("无法计算");
  });

  it("describes BOLL band position and width", () => {
    const row = byName(indicatorRows(ohlc(260, 100, 1)), "BOLL")!;
    expect(row.reading).toMatch(/上轨|下轨|通道/);
    expect(row.reading).toContain("带宽");
  });
});

describe("caveat", () => {
  it("states the readout is descriptive, not advisory", () => {
    expect(INDICATOR_CAVEAT).toContain("不构成交易建议");
  });
});

describe("indicatorSnapshot", () => {
  it("returns null below the minimum bar count", () => {
    expect(indicatorSnapshot(ohlc(MIN_BARS_FOR_INDICATORS - 1, 100, 1))).toBeNull();
  });

  it("collects every indicator when high/low are present", () => {
    const snap = indicatorSnapshot(ohlc(260, 100, 1))!;
    expect(snap.macd).not.toBeNull();
    expect(snap.boll).not.toBeNull();
    expect(snap.atr).not.toBeNull();
    expect(snap.ma.ma200).not.toBeNull();
    expect(snap.rsi).not.toBeNull();
  });

  it("omits ATR rather than deriving it from closes", () => {
    expect(indicatorSnapshot(closeOnly(260, 100, 1))!.atr).toBeNull();
  });

  it("places %B near the upper band in a strong uptrend", () => {
    expect(indicatorSnapshot(ohlc(260, 100, 1))!.boll!.pctB).toBeGreaterThan(0.7);
  });
});
