/** Plain-language read of the classic indicators shown on the price chart.
 *
 * Computation is delegated to lib/indicators (already used by the candlestick
 * chart) so both surfaces describe the same numbers.
 *
 * Descriptive, never predictive: this summarises what price has already done.
 * The project's edge scorecard has not established that these indicators have
 * statistically significant forecasting power, so the wording stays
 * observational and always carries that caveat.
 */
import { calcATR, calcBOLL, calcMA, calcMACD, calcRSI } from "@/lib/indicators";

export interface TrendBar { close: number; high?: number; low?: number }

/** Structured indicator readout — rendered as text and sent to the AI summary. */
export interface IndicatorSnapshot {
  price: number;
  macd: { dif: number; dea: number; hist: number; prevHist: number | null } | null;
  ma: { ma50: number | null; ma200: number | null };
  rsi: number | null;
  boll: { upper: number; mid: number; lower: number; pctB: number; bandwidthPct: number } | null;
  atr: { value: number; pctOfPrice: number } | null;
}

/** Minimum daily bars before the indicators mean anything. */
export const MIN_BARS_FOR_INDICATORS = 30;

const last = <T,>(a: T[]): T | undefined => a[a.length - 1];

/** Pull the latest value of every indicator into one structured object. */
export function indicatorSnapshot(bars: TrendBar[]): IndicatorSnapshot | null {
  const closes = bars.map((b) => b.close).filter((c) => Number.isFinite(c));
  if (closes.length < MIN_BARS_FOR_INDICATORS) return null;
  const price = last(closes) as number;

  const { dif, signal, histogram } = calcMACD(closes);
  const d = last(dif), sg = last(signal), h = last(histogram);
  const macdOut = d != null && sg != null && h != null
    ? { dif: d, dea: sg, hist: h, prevHist: histogram[histogram.length - 2] ?? null }
    : null;

  const b = calcBOLL(closes);
  const up = last(b.upper), mid = last(b.mid), low = last(b.lower);
  const boll = up != null && mid != null && low != null && up > low
    ? {
        upper: up, mid, lower: low,
        pctB: (price - low) / (up - low),          // 0 = lower band, 1 = upper
        bandwidthPct: ((up - low) / mid) * 100,     // band width relative to mid
      }
    : null;

  // ATR needs true high/low; a close-only series would understate the range.
  const highs = bars.map((x) => x.high), lows = bars.map((x) => x.low);
  const hasHL = highs.every((v) => Number.isFinite(v)) && lows.every((v) => Number.isFinite(v));
  const atrVal = hasHL
    ? last(calcATR(highs as number[], lows as number[], bars.map((x) => x.close)))
    : null;
  const atr = atrVal != null && price > 0
    ? { value: atrVal, pctOfPrice: (atrVal / price) * 100 }
    : null;

  return {
    price,
    macd: macdOut,
    ma: { ma50: last(calcMA(closes, 50)) ?? null, ma200: last(calcMA(closes, 200)) ?? null },
    rsi: last(calcRSI(closes)) ?? null,
    boll,
    atr,
  };
}

export function describeTrend(bars: TrendBar[]): string[] {
  const closes = bars.map((b) => b.close).filter((c) => Number.isFinite(c));
  if (closes.length < MIN_BARS_FOR_INDICATORS) {
    return [`数据点不足,无法计算指标(至少需要约 ${MIN_BARS_FOR_INDICATORS} 个交易日)。`];
  }

  const notes: string[] = [];
  const price = last(closes) as number;

  const { dif, signal, histogram } = calcMACD(closes);
  const d = last(dif), sg = last(signal), h = last(histogram);
  const prevH = histogram[histogram.length - 2];
  if (d != null && sg != null && h != null) {
    const above = d > sg;
    const zone = d > 0 ? "零轴上方" : "零轴下方";
    let cross = "";
    if (prevH != null) {
      if (prevH <= 0 && h > 0) cross = ",刚出现金叉";
      else if (prevH >= 0 && h < 0) cross = ",刚出现死叉";
    }
    const widening = prevH != null && Math.abs(h) > Math.abs(prevH);
    notes.push(
      `MACD:DIF ${above ? "位于 DEA 上方" : "跌破 DEA"},在${zone}${cross};` +
      `柱状体${h >= 0 ? "为正" : "为负"}且${widening ? "在放大" : "在收窄"},` +
      `即${above ? "上行" : "下行"}动能${widening ? "仍在增强" : "正在减弱"}。`,
    );
  }

  const ma50 = last(calcMA(closes, 50)), ma200 = last(calcMA(closes, 200));
  if (ma50 != null && ma200 != null) {
    notes.push(
      `均线:价格${price >= ma50 ? "位于 50 日均线之上" : "跌破 50 日均线"},` +
      `50 日均线${ma50 >= ma200 ? "高于" : "低于"} 200 日均线(${ma50 >= ma200 ? "多头排列" : "空头排列"})。`,
    );
  } else if (ma50 != null) {
    notes.push(
      `均线:价格${price >= ma50 ? "位于 50 日均线之上" : "跌破 50 日均线"}` +
      `(当前区间不足 200 日,长期均线未计算)。`,
    );
  }

  const r = last(calcRSI(closes));
  if (r != null) {
    const state = r >= 70 ? "进入超买区" : r <= 30 ? "进入超卖区" : "处于中性区间";
    notes.push(`RSI(14):${r.toFixed(1)},${state}。`);
  }

  const snap = indicatorSnapshot(bars);
  if (snap?.boll) {
    const { pctB, bandwidthPct, upper, lower } = snap.boll;
    const where = pctB >= 1 ? "已突破上轨"
      : pctB <= 0 ? "已跌破下轨"
      : pctB >= 0.8 ? "贴近上轨"
      : pctB <= 0.2 ? "贴近下轨"
      : "运行于通道中部";
    notes.push(
      `BOLL(20,2):价格${where}(上轨 ${upper.toFixed(2)} / 下轨 ${lower.toFixed(2)});` +
      `带宽为中轨的 ${bandwidthPct.toFixed(1)}%,${bandwidthPct < 10 ? "通道收窄,波动被压缩" : "通道较宽,波动较大"}。`,
    );
  }
  if (snap?.atr) {
    notes.push(
      `ATR(14):${snap.atr.value.toFixed(2)},约为现价的 ${snap.atr.pctOfPrice.toFixed(2)}%——` +
      `即近期日均真实波动幅度,可用于估算止损距离与仓位。`,
    );
  } else if (snap) {
    notes.push("ATR(14):当前数据缺少最高/最低价,无法计算真实波幅。");
  }

  notes.push("以上是对已发生走势的描述,不构成交易建议——本项目的信号体检尚未证实这些指标具有统计显著的预测力。");
  return notes;
}
