import { useEffect, useRef, useMemo } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";
import type { ValuationMetric, ValuationPeriod, ValuationPoint } from "@/lib/api";

export const VALUATION_PERIODS: ValuationPeriod[] = ["1Y", "3Y", "5Y", "10Y", "ALL"];

const METRIC_LABEL: Record<ValuationMetric, string> = {
  pe: "市盈率",
  pb: "市净率",
  mktcap: "总市值",
};

// Format a metric value: PE/PB → 2 decimals; market cap (in 亿) → 亿/万亿.
function formatValue(metric: ValuationMetric, v: number): string {
  if (metric === "mktcap") {
    return v >= 10000
      ? `${(v / 10000).toFixed(2)} 万亿`
      : `${v.toLocaleString("zh-CN", { maximumFractionDigits: 0 })} 亿`;
  }
  return v.toFixed(2);
}

function computeStats(points: ValuationPoint[], metric: ValuationMetric) {
  if (points.length < 2) return null;
  const current = points[points.length - 1].value;
  const values = metric === "mktcap"
    ? points.map((p) => p.value)
    : points.map((p) => p.value).filter((v) => v > 0 && v <= 200);
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const belowCount = values.filter((v) => v < current).length;
  const percentile = (belowCount / (values.length - 1)) * 100;
  return { max, min, median, percentile };
}

const PERIOD_LABEL: Record<ValuationPeriod, string> = {
  "1Y": "近1年",
  "3Y": "近3年",
  "5Y": "近5年",
  "10Y": "近10年",
  "ALL": "全部",
};

interface Props {
  points: ValuationPoint[];
  metric: ValuationMetric;
  period: ValuationPeriod;
  onPeriodChange: (p: ValuationPeriod) => void;
  loading?: boolean;
  height?: number;
}

export function ValuationChart({ points, metric, period, onPeriodChange, loading = false, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  const hasData = points.length >= 2;
  const firstVal = hasData ? points[0].value : 0;
  const lastVal = hasData ? points[points.length - 1].value : 0;
  const pctChange = firstVal ? ((lastVal - firstVal) / firstVal) * 100 : 0;
  const up = lastVal - firstVal >= 0;

  const stats = useMemo(() => computeStats(points, metric), [points, metric]);

  useEffect(() => {
    if (!ref.current || points.length < 2) return;
    const t = getChartTheme();

    const dates = points.map((p) => p.date);
    const values = points.map((p) => p.value);
    const lineColor = t.infoColor;

    const chart = echarts.init(ref.current);

    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 56, right: 12, top: 12, bottom: 28 },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: {
          fontSize: 10,
          color: t.textColor,
          hideOverlap: true,
          formatter: (val: string) => val.slice(0, 7), // YYYY-MM
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: {
          fontSize: 10,
          color: t.textColor,
          formatter: (v: number) => (metric === "mktcap" ? (v >= 10000 ? `${(v / 10000).toFixed(1)}万亿` : `${v}亿`) : v),
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: "line",
          data: values,
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
          markLine: stats ? {
            silent: true,
            symbol: "none",
            label: { fontSize: 9, position: "insideEndTop" },
            data: [
              { yAxis: stats.max, lineStyle: { color: "#ef4444", type: "dashed", width: 1 }, label: { formatter: `最高 ${formatValue(metric, stats.max)}`, color: "#ef4444" } },
              { yAxis: stats.min, lineStyle: { color: "#22c55e", type: "dashed", width: 1 }, label: { formatter: `最低 ${formatValue(metric, stats.min)}`, color: "#22c55e" } },
              { yAxis: stats.median, lineStyle: { color: "#f59e0b", type: "dashed", width: 1 }, label: { formatter: `中位数 ${formatValue(metric, stats.median)}`, color: "#f59e0b" } },
            ],
          } : undefined,
        },
      ],
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        axisPointer: { type: "cross", crossStyle: { color: t.axisColor } },
        formatter(params: { axisValue: string; value: number }[]) {
          if (!params?.length) return "";
          const date = params[0].axisValue;
          const v = params[0].value;
          return `<div style="font-size:11px;line-height:1.8">${date}<br/>${METRIC_LABEL[metric]}&nbsp;<b>${v !== undefined ? formatValue(metric, v) : "—"}</b></div>`;
        },
      },
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [points, dark, metric]);

  return (
    <div className="flex flex-col gap-3">
      {/* Current value + timeframe selector */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2">
          {hasData && !loading ? (
            <>
              <span className="text-2xl font-bold tabular-nums leading-none text-foreground">
                {formatValue(metric, lastVal)}
              </span>
              <span className={cn(
                "text-sm font-medium tabular-nums",
                up ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"
              )}>
                {up ? "+" : ""}{pctChange.toFixed(2)}%
              </span>
              <span className="text-xs text-muted-foreground">区间变化</span>
            </>
          ) : (
            <span className="text-2xl font-bold text-muted-foreground/40 tabular-nums leading-none">—</span>
          )}
        </div>
        <div className="flex gap-1 flex-wrap">
          {VALUATION_PERIODS.map((p) => (
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
        </div>
      </div>

      {/* Stats row */}
      {hasData && !loading && stats && (
        <div className="flex items-center gap-4 flex-wrap text-xs tabular-nums">
          <span className="text-red-500 dark:text-red-400">
            最高 <b>{formatValue(metric, stats.max)}</b>
          </span>
          <span className="text-emerald-600 dark:text-emerald-400">
            最低 <b>{formatValue(metric, stats.min)}</b>
          </span>
          <span className="text-amber-500 dark:text-amber-400">
            中位数 <b>{formatValue(metric, stats.median)}</b>
          </span>
          <span className="text-foreground">
            百分位 <b>{stats.percentile.toFixed(1)}%</b>
            <span className="text-muted-foreground ml-0.5">({PERIOD_LABEL[period]})</span>
          </span>
        </div>
      )}

      {/* Chart area — distinct keys so React never reuses one <div> as another
          (a reused node leaves a stale ECharts instance attached). */}
      {loading ? (
        <div key="loading" className="animate-pulse rounded-xl bg-muted" style={{ height }} />
      ) : points.length < 2 ? (
        <div
          key="empty"
          className="flex items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground text-center px-4"
          style={{ height }}
        >
          {metric === "mktcap" ? "暂无市值数据" : "暂无估值数据（指数 / ETF / 美股暂不支持）"}
        </div>
      ) : (
        <div key="chart" ref={ref} style={{ height }} />
      )}
    </div>
  );
}
