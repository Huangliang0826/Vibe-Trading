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
import { calcMA, calcMACD, calcRSI } from "@/lib/indicators";

export interface TrendBar { close: number }

/** Minimum daily bars before the indicators mean anything. */
export const MIN_BARS_FOR_INDICATORS = 30;

const last = <T,>(a: T[]): T | undefined => a[a.length - 1];

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

  notes.push("以上是对已发生走势的描述,不构成交易建议——本项目的信号体检尚未证实这些指标具有统计显著的预测力。");
  return notes;
}
