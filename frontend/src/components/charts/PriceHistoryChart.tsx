import { useEffect, useMemo, useRef, useState } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";
import { calcMA, calcMACD } from "@/lib/indicators";
import { MIN_BARS_FOR_INDICATORS, describeTrend, indicatorSnapshot } from "@/lib/trend-narrative";
import { api } from "@/lib/api";
import type { PriceHistoryBar, PriceHistoryPeriod, WatchlistHistoryMetrics, WatchlistQuote } from "@/lib/api";

export const PRICE_PERIODS: PriceHistoryPeriod[] = ["1D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "4Y", "5Y", "ALL"];

interface Props {
  bars: PriceHistoryBar[];
  period: PriceHistoryPeriod;
  onPeriodChange: (p: PriceHistoryPeriod) => void;
  loading?: boolean;
  height?: number;
  showRisk?: boolean;
  quote?: WatchlistQuote | null;
  metrics?: WatchlistHistoryMetrics | null;
  /** Shown to the AI summary so it names the right instrument. */
  symbol?: string;
}

/** Max drawdown over the displayed window + recovery time of that episode.
 *
 * maxDD: deepest peak-to-trough drop (negative fraction). recoveryDays: calendar
 * days from the trough back up to the prior peak; null if not yet recovered, in
 * which case ``sinceTroughDays`` counts days from the trough to the last bar. */
function computeDrawdown(bars: PriceHistoryBar[]): {
  maxDD: number; recovered: boolean; recoveryDays: number | null;
  sincePeakDays: number; recoveredPct: number;
} | null {
  if (bars.length < 2) return null;
  let peak = bars[0].close, peakIdx = 0;
  let maxDD = 0, troughIdx = -1, ddPeakIdx = 0;
  for (let i = 0; i < bars.length; i++) {
    const c = bars[i].close;
    if (c > peak) { peak = c; peakIdx = i; }
    const dd = peak > 0 ? c / peak - 1 : 0;
    if (dd < maxDD) { maxDD = dd; troughIdx = i; ddPeakIdx = peakIdx; }
  }
  if (troughIdx < 0 || maxDD === 0) {
    return { maxDD: 0, recovered: true, recoveryDays: 0, sincePeakDays: 0, recoveredPct: 100 };
  }
  const dayDiff = (a: string, b: string) =>
    Math.round((new Date(b.slice(0, 10)).getTime() - new Date(a.slice(0, 10)).getTime()) / 86400000);
  const peakValue = bars[ddPeakIdx].close;
  for (let j = troughIdx + 1; j < bars.length; j++) {
    if (bars[j].close >= peakValue) {
      return { maxDD, recovered: true, recoveryDays: dayDiff(bars[troughIdx].date, bars[j].date), sincePeakDays: 0, recoveredPct: 100 };
    }
  }
  // Not recovered: days since the PEAK (how long this drawdown has lasted) +
  // how far back up from the trough toward the prior peak.
  const troughValue = bars[troughIdx].close;
  const span = peakValue - troughValue;
  const last = bars[bars.length - 1].close;
  const recoveredPct = span > 0 ? Math.min(Math.max((last - troughValue) / span * 100, 0), 100) : 0;
  return { maxDD, recovered: false, recoveryDays: null,
           sincePeakDays: dayDiff(bars[ddPeakIdx].date, bars[bars.length - 1].date), recoveredPct };
}

export function computeDailyDca(bars: PriceHistoryBar[]): {
  totalReturn: number;
  maxLoss: number;
  contributions: number;
} | null {
  if (bars.length < 2 || bars[0].close <= 0) return null;

  let wealth = 1;
  let contributed = 1;
  let contributionDays = 1;
  let lastContributionDate = bars[0].date.slice(0, 10);
  const nav = [1];

  for (let i = 1; i < bars.length; i++) {
    const prevClose = bars[i - 1].close;
    const close = bars[i].close;
    if (prevClose > 0) {
      wealth *= close / prevClose;
    }

    const currentDate = bars[i].date.slice(0, 10);
    if (currentDate !== lastContributionDate) {
      wealth += 1;
      contributed += 1;
      contributionDays += 1;
      lastContributionDate = currentDate;
    }
    nav.push(wealth / contributed);
  }

  return {
    totalReturn: nav[nav.length - 1] - 1,
    maxLoss: Math.min(...nav.map((value) => value - 1)),
    contributions: contributionDays,
  };
}

// Change over the displayed range — computed from the exact plotted bars so
// the number always matches the line (red = up / green = down, CN convention).
function changeClass(up: boolean) {
  return up ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400";
}

// Shorten an axis tick label based on the active period.
function formatAxisLabel(val: string, period: PriceHistoryPeriod): string {
  if (val.includes(" ")) {
    const [d, time] = val.split(" ");
    return period === "1D" ? time : d.slice(5);
  }
  if (period === "5Y" || period === "ALL") return val.slice(0, 7); // YYYY-MM
  return val.slice(5); // MM-DD
}

export function PriceHistoryChart({ bars, period, onPeriodChange, loading = false, height = 300, showRisk = false, quote = null, metrics = null, symbol = "" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();
  // Off by default: the overlays are opt-in, and they cost a third chart grid.
  const [showIndicators, setShowIndicators] = useState(false);
  // Intraday bars are not daily closes, so MA/MACD periods would be meaningless.
  const indicatorsAvailable = period !== "1D" && bars.length >= MIN_BARS_FOR_INDICATORS;
  const indicatorsOn = showIndicators && indicatorsAvailable;
  const trendNotes = useMemo(
    () => (indicatorsOn ? describeTrend(bars) : []),
    [indicatorsOn, bars],
  );
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const runAiSummary = async () => {
    const snapshot = indicatorSnapshot(bars);
    if (!snapshot) { setAiError("数据点不足,无法生成总结。"); return; }
    setAiBusy(true); setAiError(null);
    try {
      const r = await api.getIndicatorSummary({ symbol, name: symbol, period, snapshot });
      setAiSummary(r.summary);
    } catch (e) {
      setAiError(e instanceof Error ? e.message : "AI 总结失败");
    } finally {
      setAiBusy(false);
    }
  };

  const hasData = bars.length >= 2;
  const firstClose = hasData ? bars[0].close : 0;
  const lastClose = hasData ? bars[bars.length - 1].close : 0;
  const hasLiveDayQuote = period === "1D" && !!quote && quote.price > 0 && quote.prev_close > 0;
  const displayClose = hasLiveDayQuote ? quote.price : lastClose;
  const absChange = hasLiveDayQuote ? quote.price - quote.prev_close : lastClose - firstClose;
  const pctChange = hasLiveDayQuote ? (absChange / quote.prev_close) * 100 : firstClose ? (absChange / firstClose) * 100 : 0;
  const up = absChange >= 0;
  const changeLabel = hasLiveDayQuote ? "今日涨跌" : `${period} 区间涨跌`;
  const dd = showRisk && hasData ? computeDrawdown(bars) : null;
  const localDailyDca = showRisk && hasData && period !== "1D" ? computeDailyDca(bars) : null;
  const buyAndHold = metrics?.buy_and_hold ?? null;
  const dailyDca = period !== "1D" ? metrics?.daily_dca ?? localDailyDca : null;
  const maxDrawdown = buyAndHold?.max_drawdown ?? dd?.maxDD ?? null;
  const dailyDcaReturn = dailyDca && ("total_return" in dailyDca ? dailyDca.total_return : dailyDca.totalReturn);
  const dailyDcaMaxLoss = dailyDca && ("max_loss" in dailyDca ? dailyDca.max_loss : dailyDca.maxLoss);
  const dailyDcaContributions = dailyDca?.contributions ?? 0;

  useEffect(() => {
    if (!ref.current || bars.length < 2) return;
    const t = getChartTheme();

    const dates = bars.map((b) => b.date);
    const closes = bars.map((b) => b.close);
    const volumes = bars.map((b) => b.volume);

    const positive = closes[closes.length - 1] >= closes[0];
    const lineColor = positive ? t.upColor : t.downColor;

    // Indicator overlays (opt-in). MACD gets its own grid below volume.
    const ma50 = indicatorsOn ? calcMA(closes, 50) : [];
    const ma200 = indicatorsOn ? calcMA(closes, 200) : [];
    const m = indicatorsOn ? calcMACD(closes) : null;

    const chart = echarts.init(ref.current);

    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: indicatorsOn
        ? [
            { left: 52, right: 8, top: 8, height: "46%" },
            { left: 52, right: 8, top: "58%", height: "12%" },
            { left: 52, right: 8, top: "76%", height: "20%" },
          ]
        : [
            { left: 52, right: 8, top: 8, bottom: 40, height: "60%" },
            { left: 52, right: 8, top: "76%", bottom: 0, height: "18%" },
          ],
      xAxis: [
        {
          type: "category",
          data: dates,
          gridIndex: 0,
          axisLine: { lineStyle: { color: t.axisColor } },
          axisLabel: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        {
          type: "category",
          data: dates,
          gridIndex: 1,
          axisLine: { lineStyle: { color: t.axisColor } },
          axisLabel: indicatorsOn ? { show: false } : {
            fontSize: 10,
            color: t.textColor,
            interval: "auto",
            hideOverlap: true,
            formatter: (val: string) => formatAxisLabel(val, period),
          },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        ...(indicatorsOn ? [{
          type: "category",
          data: dates,
          gridIndex: 2,
          axisLine: { lineStyle: { color: t.axisColor } },
          axisLabel: {
            fontSize: 10,
            color: t.textColor,
            interval: "auto",
            hideOverlap: true,
            formatter: (val: string) => formatAxisLabel(val, period),
          },
          axisTick: { show: false },
          splitLine: { show: false },
        }] : []),
      ],
      yAxis: [
        {
          type: "value",
          scale: true,
          gridIndex: 0,
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { fontSize: 10, color: t.textColor },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: "value",
          gridIndex: 1,
          splitLine: { show: false },
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        ...(indicatorsOn ? [{
          type: "value",
          scale: true,
          gridIndex: 2,
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { fontSize: 9, color: t.textColor },
          axisLine: { show: false },
          axisTick: { show: false },
        }] : []),
      ],
      series: [
        {
          type: "line",
          data: closes,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: "none",
          smooth: false,
          lineStyle: { color: lineColor, width: 1.5 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: lineColor + "30" },
                { offset: 1, color: lineColor + "00" },
              ],
            },
          },
        },
        {
          type: "bar",
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: {
            // Per-bar up/down color: close >= prev close → up (red, CN), else down (green)
            color: (params: { dataIndex: number }) => {
              const i = params.dataIndex;
              const prev = i > 0 ? closes[i - 1] : closes[i];
              return closes[i] >= prev ? t.volumeUp : t.volumeDown;
            },
          },
          barMaxWidth: 6,
        },
        ...(indicatorsOn && m ? [
          { type: "line", name: "MA50", data: ma50, xAxisIndex: 0, yAxisIndex: 0,
            symbol: "none", lineStyle: { color: "#f59e0b", width: 1 }, z: 3 },
          { type: "line", name: "MA200", data: ma200, xAxisIndex: 0, yAxisIndex: 0,
            symbol: "none", lineStyle: { color: "#8b5cf6", width: 1 }, z: 3 },
          { type: "bar", name: "MACD", data: m.histogram, xAxisIndex: 2, yAxisIndex: 2,
            barMaxWidth: 6,
            itemStyle: {
              color: (p: { data: number | null }) =>
                (p.data ?? 0) >= 0 ? t.volumeUp : t.volumeDown,
            } },
          { type: "line", name: "DIF", data: m.dif, xAxisIndex: 2, yAxisIndex: 2,
            symbol: "none", lineStyle: { color: t.upColor, width: 1 } },
          { type: "line", name: "DEA", data: m.signal, xAxisIndex: 2, yAxisIndex: 2,
            symbol: "none", lineStyle: { color: "#f59e0b", width: 1 } },
        ] : []),
      ],
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // Keep the crosshair guide lines, but hide the dark value/date label
        // boxes on the axes — the light tooltip already shows price + date.
        axisPointer: { type: "cross", label: { show: false }, crossStyle: { color: t.axisColor } },
        formatter(params: { axisValue: string; value: number; seriesType: string }[]) {
          if (!params?.length) return "";
          const date = params[0].axisValue;
          const price = params.find((p) => p.seriesType === "line")?.value;
          const base = bars[0]?.close ?? 0;
          const pct = base && price !== undefined ? ((price - base) / base) * 100 : 0;
          const pctStr = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
          return `<div style="font-size:11px;line-height:1.8">${date}<br/>价格&nbsp;<b>${price !== undefined ? price.toFixed(2) : "—"}</b>&nbsp;<span style="opacity:.7">(${pctStr})</span></div>`;
        },
      },
      // Global axisPointer: link the crosshair across both grids but hide the
      // dark value/date label boxes on every axis (tooltip already shows them).
      axisPointer: { link: [{ xAxisIndex: "all" }], label: { show: false } },
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [bars, dark, period, indicatorsOn]);

  return (
    <div className="flex flex-col gap-3">
      {/* Change over range + timeframe selector */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2">
          {hasData && !loading ? (
            <>
              <span className="text-2xl font-bold tabular-nums leading-none text-foreground">
                {displayClose.toFixed(2)}
              </span>
              <span className={cn("text-base font-medium tabular-nums text-muted-foreground")}>
                {changeLabel}：<span className={changeClass(up)}>{up ? "+" : ""}{pctChange.toFixed(2)}%</span>
              </span>
            </>
          ) : (
            <span className="text-2xl font-bold text-muted-foreground/40 tabular-nums leading-none">—</span>
          )}
        </div>
        <div className="flex gap-1 flex-wrap">
          {PRICE_PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => onPeriodChange(p)}
              className={cn(
                "px-2.5 py-0.5 rounded-md text-xs font-medium transition-colors",
                p === period
                  ? "bg-primary/10 text-primary border border-primary/30"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted border border-transparent"
              )}
            >
              {p}
            </button>
          ))}
          <button
            onClick={() => setShowIndicators((v) => !v)}
            disabled={!indicatorsAvailable}
            title={indicatorsAvailable
              ? "叠加 MA50 / MA200 与 MACD,并给出走势文字解读"
              : "指标需要日线数据(1D 为分时)且至少约 30 个交易日"}
            className={cn(
              "ml-1 px-2.5 py-0.5 rounded-md text-xs font-medium transition-colors border disabled:opacity-40",
              indicatorsOn
                ? "bg-primary/10 text-primary border-primary/30"
                : "text-muted-foreground hover:text-foreground hover:bg-muted border-transparent",
            )}
          >
            指标
          </button>
        </div>
      </div>

      {/* Risk metrics over the displayed window: max drawdown + recovery time */}
      {(dd || buyAndHold || dailyDca) && !loading && (
        <div className="flex items-center gap-x-4 gap-y-1 text-[11px] -mt-1 flex-wrap">
          <span className="text-muted-foreground">
            最大回撤{" "}
            <b className={cn("tabular-nums", (maxDrawdown ?? 0) < 0 ? "text-red-500 dark:text-red-400" : "text-foreground")}>
              {maxDrawdown == null ? "—" : `${(maxDrawdown * 100).toFixed(1)}%`}
            </b>
          </span>
          {dd && <span className="text-muted-foreground">
            回撤修复{" "}
            {dd.maxDD === 0 ? (
              <b className="text-foreground">—</b>
            ) : dd.recovered ? (
              <b className="tabular-nums text-emerald-600 dark:text-emerald-400">{dd.recoveryDays} 天</b>
            ) : (
              <b className="tabular-nums text-amber-600 dark:text-amber-400">暂未修复（距高点 {dd.sincePeakDays} 天 · 已恢复 {dd.recoveredPct.toFixed(0)}%）</b>
            )}
          </span>}
          {dailyDca && (
            <>
              <span className="text-muted-foreground">
                每日定投收益{" "}
                <b className={cn("tabular-nums", (dailyDcaReturn ?? 0) >= 0 ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                  {(dailyDcaReturn ?? 0) >= 0 ? "+" : ""}{((dailyDcaReturn ?? 0) * 100).toFixed(1)}%
                </b>
              </span>
              <span className="text-muted-foreground">
                每日定投最大亏损{" "}
                <b className={cn("tabular-nums", (dailyDcaMaxLoss ?? 0) < 0 ? "text-red-500 dark:text-red-400" : "text-foreground")}>
                  {((dailyDcaMaxLoss ?? 0) * 100).toFixed(1)}%
                </b>
                <span className="ml-1 text-muted-foreground/70">({dailyDcaContributions} 次)</span>
              </span>
            </>
          )}
        </div>
      )}

      {/* Chart area — distinct keys so React never reuses one <div> as another
          (a reused node leaves a stale ECharts instance attached). */}
      {loading ? (
        <div key="loading" className="animate-pulse rounded-xl bg-muted" style={{ height }} />
      ) : bars.length < 2 ? (
        <div
          key="empty"
          className="flex items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground"
          style={{ height }}
        >
          暂无数据
        </div>
      ) : (
        <div key="chart" ref={ref} style={{ height: indicatorsOn ? height + 90 : height }} />
      )}

      {indicatorsOn && trendNotes.length > 0 && (
        <div className="mt-2 rounded-lg border bg-muted/20 px-3 py-2.5">
          <div className="mb-1 flex items-center gap-3 text-[10px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: "#f59e0b" }} />MA50 / DEA
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: "#8b5cf6" }} />MA200
            </span>
            <span>下方副图为 MACD(12,26,9)</span>
          </div>
          <ul className="space-y-1 text-[11px] leading-5 text-muted-foreground">
            {trendNotes.map((note, i) => (
              <li key={i} className={cn(i === trendNotes.length - 1 && "text-muted-foreground/70")}>{note}</li>
            ))}
          </ul>

          <div className="mt-2.5 border-t pt-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium">AI 总结 · DeepSeek</span>
              <button
                onClick={runAiSummary}
                disabled={aiBusy}
                className="rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground transition hover:text-foreground disabled:opacity-50"
              >
                {aiBusy ? "生成中…" : aiSummary ? "重新生成" : "生成总结"}
              </button>
            </div>
            {aiError && <p className="mt-1 text-[11px] text-red-500">{aiError}</p>}
            {aiSummary && (
              <p className="mt-1.5 whitespace-pre-wrap text-[11px] leading-5 text-foreground/90">{aiSummary}</p>
            )}
            {!aiSummary && !aiError && !aiBusy && (
              <p className="mt-1 text-[11px] text-muted-foreground/70">
                把上面全部指标交给 DeepSeek 归纳趋势并指出指标间的印证或矛盾。
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
