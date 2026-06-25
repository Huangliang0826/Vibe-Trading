import { useEffect, useRef } from "react";
import type { PaperTrade, PriceHistoryBar, PriceHistoryPeriod } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";
import { PRICE_PERIODS } from "@/components/charts/PriceHistoryChart";

interface Props {
  bars: PriceHistoryBar[];
  trades?: PaperTrade[] | null;
  period: PriceHistoryPeriod;
  onPeriodChange: (period: PriceHistoryPeriod) => void;
  loading?: boolean;
  height?: number;
}

const BUY_MARKER_COLOR = "#ef4444";

function formatAxisLabel(val: string, period: PriceHistoryPeriod): string {
  if (val.includes(" ")) {
    const [d, time] = val.split(" ");
    return period === "1D" ? time : d.slice(5);
  }
  if (period === "5Y" || period === "ALL") return val.slice(0, 7);
  return val.slice(5);
}

function fmtPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function markerTooltip(params: { data: [string, number, string, number] }, label: string) {
  const [date, , symbol, price] = params.data;
  return `<b>${date}</b><br/>${label} ${symbol}<br/>价格：${price}`;
}

export function PaperHoldingPriceChart({
  bars,
  trades = [],
  period,
  onPeriodChange,
  loading = false,
  height = 320,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();
  const hasData = bars.length >= 2;
  const firstClose = hasData ? bars[0].close : 0;
  const lastClose = hasData ? bars[bars.length - 1].close : 0;
  const pctChange = firstClose > 0 ? (lastClose / firstClose - 1) * 100 : 0;
  const up = pctChange >= 0;

  useEffect(() => {
    if (!ref.current || bars.length < 2) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    const dates = bars.map((bar) => bar.date.slice(0, 10));
    const closes = bars.map((bar) => Number(bar.close));
    const volumes = bars.map((bar) => Number(bar.volume));
    const closeByDate = new Map(dates.map((date, index) => [date, closes[index]]));
    const buyMarkers: unknown[] = [];
    const sellMarkers: unknown[] = [];

    for (const trade of trades || []) {
      const entryDate = String(trade.entry_time).slice(0, 10);
      const exitDate = String(trade.exit_time).slice(0, 10);
      const entryY = closeByDate.get(entryDate);
      const exitY = closeByDate.get(exitDate);
      const entryIsBuy = trade.direction >= 0;
      if (entryY !== undefined) {
        (entryIsBuy ? buyMarkers : sellMarkers).push([entryDate, entryY, trade.symbol, trade.entry_price]);
      }
      if (exitY !== undefined) {
        (entryIsBuy ? sellMarkers : buyMarkers).push([exitDate, exitY, trade.symbol, trade.exit_price]);
      }
    }

    const lineColor = up ? t.upColor : t.downColor;
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
          name: "价格",
          type: "line",
          data: closes,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: "none",
          smooth: false,
          z: 3,
          lineStyle: { color: lineColor, width: 1.5 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: `${lineColor}30` },
                { offset: 1, color: `${lineColor}00` },
              ],
            },
          },
        },
        {
          name: "买入",
          type: "scatter",
          data: buyMarkers,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: "triangle",
          symbolSize: 12,
          z: 10,
          itemStyle: { color: BUY_MARKER_COLOR, borderColor: "#fff", borderWidth: 1 },
          tooltip: { formatter: (params: { data: [string, number, string, number] }) => markerTooltip(params, "买入") },
        },
        {
          name: "卖出",
          type: "scatter",
          data: sellMarkers,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: "triangle",
          symbolRotate: 180,
          symbolSize: 12,
          z: 10,
          itemStyle: { color: t.downColor, borderColor: "#fff", borderWidth: 1 },
          tooltip: { formatter: (params: { data: [string, number, string, number] }) => markerTooltip(params, "卖出") },
        },
        {
          type: "bar",
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: {
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
          const price = params.find((item) => item.seriesType === "line")?.value;
          const base = closes[0] ?? 0;
          const change = base && price !== undefined ? (price / base - 1) * 100 : 0;
          return `<div style="font-size:11px;line-height:1.8">${date}<br/>价格&nbsp;<b>${price !== undefined ? price.toFixed(2) : "—"}</b>&nbsp;<span style="opacity:.7">(${fmtPct(change)})</span></div>`;
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [bars, dark, period, trades, up]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2">
          {hasData && !loading ? (
            <>
              <span className="text-2xl font-bold tabular-nums leading-none text-foreground">
                {lastClose.toFixed(2)}
              </span>
              <span className={cn("text-base font-medium tabular-nums", up ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                {fmtPct(pctChange)}
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
                  : "text-muted-foreground hover:text-foreground hover:bg-muted border border-transparent",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="animate-pulse rounded-xl bg-muted" style={{ height }} />
      ) : bars.length < 2 ? (
        <div
          className="flex items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground"
          style={{ height }}
        >
          暂无价格数据
        </div>
      ) : (
        <div ref={ref} style={{ height }} />
      )}
    </div>
  );
}
