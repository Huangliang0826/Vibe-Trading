import { useEffect, useRef } from "react";
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
