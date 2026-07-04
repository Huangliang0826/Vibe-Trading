import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";
import type { PriceHistoryPeriod, WatchlistHistoryResponse } from "@/lib/api";

export const PRICE_PERIODS: PriceHistoryPeriod[] = ["1D", "1M", "YTD", "1Y", "3Y", "5Y", "ALL"];

interface Props {
  history: WatchlistHistoryResponse | null;
  period: PriceHistoryPeriod;
  onPeriodChange: (p: PriceHistoryPeriod) => void;
  loading?: boolean;
  height?: number;
  showRisk?: boolean;
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

export function PriceHistoryChart({ history, period, onPeriodChange, loading = false, height = 300, showRisk = false }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  const bars = history?.bars ?? [];
  const hasData = bars.length >= 2;
  const lastClose = hasData ? bars[bars.length - 1].close : 0;
  const displayClose = history?.endpoint?.value ?? lastClose;
  const pctChange = history?.metrics.interval_return_pct ?? null;
  const up = (pctChange ?? 0) >= 0;
  const changeLabel = period === "1D" ? "今日涨跌" : `${period} 区间涨跌`;

  useEffect(() => {
    if (!ref.current || bars.length < 2) return;
    const t = getChartTheme();

    const dates = bars.map((b) => b.date);
    const closes = bars.map((b) => b.close);
    const volumes = bars.map((b) => b.volume ?? null);

    const positive = (history?.metrics.interval_return_pct ?? 0) >= 0;
    const lineColor = positive ? t.upColor : t.downColor;

    const chart = echarts.init(ref.current);

    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: [
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
          axisLabel: {
            fontSize: 10,
            color: t.textColor,
            interval: "auto",
            hideOverlap: true,
            formatter: (val: string) => formatAxisLabel(val, period),
          },
          axisTick: { show: false },
          splitLine: { show: false },
        },
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
      ],
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        axisPointer: { type: "cross", crossStyle: { color: t.axisColor } },
        formatter(params: { axisValue: string; value: number; seriesType: string }[]) {
          if (!params?.length) return "";
          const date = params[0].axisValue;
          const price = params.find((p) => p.seriesType === "line")?.value;
          return `<div style="font-size:11px;line-height:1.8">${date}<br/>价格&nbsp;<b>${price !== undefined ? price.toFixed(2) : "—"}</b></div>`;
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [bars, dark, history?.metrics.interval_return_pct, period]);

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
                {changeLabel}：{pctChange == null ? (
                  <span className="text-muted-foreground">数据不足</span>
                ) : (
                  <span className={changeClass(up)}>{up ? "+" : ""}{pctChange.toFixed(2)}%</span>
                )}
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
        </div>
      </div>

      {showRisk && history && hasData && !loading && (
        <div className="flex items-center gap-x-4 gap-y-1 text-[11px] -mt-1 flex-wrap">
          <span className="text-muted-foreground">
            买入持有最大亏损 <MetricValue value={history.metrics.buy_hold_max_loss_pct} />
          </span>
          <span className="text-muted-foreground">
            最大回撤 <MetricValue value={history.metrics.max_drawdown_pct} />
          </span>
          {period !== "1D" && (
            <>
              <span className="text-muted-foreground">
                每日定投收益 <MetricValue value={history.metrics.dca_return_pct} signed />
              </span>
              <span className="text-muted-foreground">
                每日定投最大亏损 <MetricValue value={history.metrics.dca_max_loss_pct} />
                {history.metrics.dca_contribution_count != null && (
                  <span className="ml-1 text-muted-foreground/70">({history.metrics.dca_contribution_count} 次)</span>
                )}
              </span>
            </>
          )}
        </div>
      )}

      {history && history.data_status.issues.length > 0 && !loading && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-amber-600 dark:text-amber-400">
          {history.data_status.issues.map((issue) => <span key={`${issue.code}:${issue.timestamp ?? ""}`}>{issue.message}</span>)}
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
        <div key="chart" ref={ref} style={{ height }} />
      )}
    </div>
  );
}

function MetricValue({ value, signed = false }: { value: number | null; signed?: boolean }) {
  if (value == null) return <b className="text-muted-foreground">—</b>;
  const prefix = signed && value >= 0 ? "+" : "";
  return (
    <b className={cn("tabular-nums", value < 0 ? "text-red-500 dark:text-red-400" : "text-foreground")}>
      {prefix}{value.toFixed(1)}%
    </b>
  );
}
