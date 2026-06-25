import { useEffect, useMemo, useRef, useState } from "react";
import type { EquityPoint, PaperTrade } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";

interface Props {
  data: EquityPoint[];
  trades?: PaperTrade[] | null;
  height?: number;
}

type DisplayMode = "equity" | "return";

function money(value: number) {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(value: number) {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function shortDate(value: string) {
  if (value.length >= 10) return value.slice(5, 10);
  return value;
}

const BUY_MARKER_COLOR = "#ef4444";
const EQUITY_LINE_COLOR = "#94a3b8";

export function PaperEquityChart({ data, trades = [], height = 300 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();
  const [mode, setMode] = useState<DisplayMode>("return");

  const stats = useMemo(() => {
    const values = data.map((point) => Number(point.equity)).filter((value) => Number.isFinite(value));
    if (values.length < 2) return null;
    const first = values[0];
    const last = values[values.length - 1];
    const totalReturn = first > 0 ? last / first - 1 : 0;
    const maxDrawdown = Math.min(...data.map((point) => Number(point.drawdown)).filter((value) => Number.isFinite(value)));
    return {
      first,
      last,
      totalReturn,
      maxDrawdown,
      up: last >= first,
    };
  }, [data]);

  useEffect(() => {
    if (!ref.current || data.length < 2 || !stats) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    const dates = data.map((point) => point.time);
    const values = data.map((point) => Number(point.equity));
    const valueByDate = new Map(dates.map((date, index) => [date, values[index]]));
    const lineData = mode === "return"
      ? values.map((value) => stats.first > 0 ? (value / stats.first - 1) * 100 : 0)
      : values;
    const yForDate = (date: string) => {
      const equity = valueByDate.get(date);
      if (!Number.isFinite(equity)) return null;
      return mode === "return" ? ((equity as number) / stats.first - 1) * 100 : equity as number;
    };
    const buyMarkers: unknown[] = [];
    const sellMarkers: unknown[] = [];
    for (const trade of trades || []) {
      const entryDate = String(trade.entry_time).slice(0, 10);
      const exitDate = String(trade.exit_time).slice(0, 10);
      const entryY = yForDate(entryDate);
      const exitY = yForDate(exitDate);
      const entryIsBuy = trade.direction >= 0;
      if (entryY !== null) {
        (entryIsBuy ? buyMarkers : sellMarkers).push([entryDate, entryY, trade.symbol, trade.entry_price]);
      }
      if (exitY !== null) {
        (entryIsBuy ? sellMarkers : buyMarkers).push([exitDate, exitY, trade.symbol, trade.exit_price]);
      }
    }
    const lineColor = EQUITY_LINE_COLOR;

    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 8, right: 8, top: 12, bottom: 28, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        axisPointer: { type: "line", lineStyle: { color: t.axisColor } },
        formatter(params: { axisValue: string; value: number; marker: string }[]) {
          const item = params?.[0];
          if (!item) return "";
          const idx = dates.indexOf(item.axisValue);
          const equity = values[idx] ?? item.value;
          const ret = stats.first > 0 ? equity / stats.first - 1 : 0;
          return [
            `<b>${item.axisValue}</b>`,
            `${item.marker} 净值：<b>${money(equity)}</b>`,
            `收益率：<b>${pct(ret)}</b>`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: {
          color: t.textColor,
          fontSize: 10,
          hideOverlap: true,
          formatter: shortDate,
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: t.textColor,
          fontSize: 10,
          formatter: mode === "return"
            ? (value: number) => `${value.toFixed(0)}%`
            : (value: number) => value >= 1000 ? `${Math.round(value / 1000)}k` : String(Math.round(value)),
        },
        splitLine: { lineStyle: { color: t.gridColor } },
      },
      series: [
        {
          name: mode === "return" ? "收益率" : "组合净值",
          type: "line",
          data: lineData,
          symbol: "none",
          smooth: true,
          z: 3,
          lineStyle: { color: lineColor, width: 2 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: `${lineColor}2f` },
                { offset: 1, color: `${lineColor}00` },
              ],
            },
          },
        },
        {
          name: "买入",
          type: "scatter",
          data: buyMarkers,
          symbol: "triangle",
          symbolSize: 12,
          z: 10,
          itemStyle: { color: BUY_MARKER_COLOR, borderColor: "#fff", borderWidth: 1 },
          tooltip: {
            formatter(params: { data: [string, number, string, number] }) {
              const [date, , symbol, price] = params.data;
              return `<b>${date}</b><br/>买入 ${symbol}<br/>价格：${price}`;
            },
          },
        },
        {
          name: "卖出",
          type: "scatter",
          data: sellMarkers,
          symbol: "triangle",
          symbolRotate: 180,
          symbolSize: 12,
          z: 10,
          itemStyle: { color: t.downColor, borderColor: "#fff", borderWidth: 1 },
          tooltip: {
            formatter(params: { data: [string, number, string, number] }) {
              const [date, , symbol, price] = params.data;
              return `<b>${date}</b><br/>卖出 ${symbol}<br/>价格：${price}`;
            },
          },
        },
      ],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [data, dark, mode, stats, trades]);

  if (!stats) {
    return <div className="p-4 text-sm text-muted-foreground">暂无收益曲线数据</div>;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs text-muted-foreground">最终净值</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">{money(stats.last)}</span>
            <span className={cn("text-sm font-medium tabular-nums", stats.up ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
              {pct(stats.totalReturn)}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            初始 {money(stats.first)} · 最大亏损 {pct(stats.maxDrawdown)}
          </p>
        </div>
        <div className="inline-flex w-fit rounded-md border bg-background p-1">
          {[
            ["equity", "净值"],
            ["return", "收益率"],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setMode(value as DisplayMode)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                mode === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div ref={ref} style={{ height }} />
    </div>
  );
}
