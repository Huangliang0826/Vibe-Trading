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

export interface IndicatorRow {
  /** Indicator label, e.g. "MACD (12,26,9)". */
  name: string;
  /** The raw numbers, kept compact enough for a table cell. */
  value: string;
  /** What those numbers currently say. */
  reading: string;
  /** Directional colouring for the reading cell. */
  tone: "up" | "down" | "neutral";
}

/** The caveat shown under the table — these indicators describe, not predict. */
export const INDICATOR_CAVEAT =
  "以上为对已发生走势的描述,不构成交易建议——本项目的信号体检尚未证实这些指标具有统计显著的预测力。";

const n2 = (v: number) => v.toFixed(2);

/** Structured readout for the indicator table. */
export function indicatorRows(bars: TrendBar[]): IndicatorRow[] {
  const snap = indicatorSnapshot(bars);
  if (!snap) return [];
  const rows: IndicatorRow[] = [];

  if (snap.macd) {
    const { dif, dea, hist, prevHist } = snap.macd;
    const above = dif > dea;
    const widening = prevHist != null && Math.abs(hist) > Math.abs(prevHist);
    let cross = "";
    if (prevHist != null) {
      if (prevHist <= 0 && hist > 0) cross = "金叉 · ";
      else if (prevHist >= 0 && hist < 0) cross = "死叉 · ";
    }
    rows.push({
      name: "MACD (12,26,9)",
      value: `DIF ${n2(dif)} / DEA ${n2(dea)}`,
      reading: `${cross}${dif > 0 ? "零轴上方" : "零轴下方"},${above ? "多头" : "空头"}动能${widening ? "增强" : "减弱"}`,
      tone: above ? "up" : "down",
    });
  }

  const { ma50, ma200 } = snap.ma;
  if (ma50 != null) {
    const bull = ma200 != null ? ma50 >= ma200 : snap.price >= ma50;
    rows.push({
      name: "均线 MA50 / MA200",
      value: ma200 != null ? `${n2(ma50)} / ${n2(ma200)}` : `${n2(ma50)} / —`,
      reading: ma200 != null
        ? `${bull ? "多头排列" : "空头排列"},价格${snap.price >= ma50 ? "在 MA50 之上" : "跌破 MA50"}`
        : `价格${snap.price >= ma50 ? "在 MA50 之上" : "跌破 MA50"}(区间不足 200 日)`,
      tone: bull ? "up" : "down",
    });
  }

  if (snap.rsi != null) {
    const r = snap.rsi;
    rows.push({
      name: "RSI (14)",
      value: r.toFixed(1),
      reading: r >= 70 ? "超买区" : r <= 30 ? "超卖区" : "中性区间",
      tone: r >= 70 ? "down" : r <= 30 ? "up" : "neutral",
    });
  }

  if (snap.boll) {
    const { pctB, bandwidthPct, upper, lower } = snap.boll;
    const where = pctB >= 1 ? "突破上轨" : pctB <= 0 ? "跌破下轨"
      : pctB >= 0.8 ? "贴近上轨" : pctB <= 0.2 ? "贴近下轨" : "通道中部";
    rows.push({
      name: "BOLL (20,2)",
      value: `${n2(lower)} – ${n2(upper)}`,
      reading: `${where},带宽 ${bandwidthPct.toFixed(1)}%(${bandwidthPct < 10 ? "收窄" : "较宽"})`,
      tone: pctB >= 0.8 ? "up" : pctB <= 0.2 ? "down" : "neutral",
    });
  }

  rows.push(snap.atr
    ? {
        name: "ATR (14)",
        value: `${n2(snap.atr.value)}(${snap.atr.pctOfPrice.toFixed(2)}%)`,
        reading: "日均真实波幅,可作止损距离参考",
        tone: "neutral",
      }
    : { name: "ATR (14)", value: "—", reading: "数据缺少最高/最低价,无法计算", tone: "neutral" });

  return rows;
}
