import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { QuintileResponse } from "@/lib/api";

const Q_COLORS = ["#10b981", "#34d399", "#94a3b8", "#f97316", "#de6a48"];
const LS_COLOR = "#6366f1";

interface Props {
  data: QuintileResponse;
  height?: number;
}

export function QuintileChart({ data, height = 300 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();
    const dates = data.dates.map((d) => d.slice(0, 10));
    const lq = (data as any).long_q ?? "Q2";
    const sq = (data as any).short_q ?? "Q5";
    const lsLabel = `多空(${lq}-${sq})`;

    const series: any[] = [];
    const quintiles = ["Q1", "Q2", "Q3", "Q4", "Q5"];
    quintiles.forEach((q, i) => {
      const vals = data.quintile_returns[q];
      if (!vals) return;
      const isLeg = q === lq || q === sq;
      series.push({
        name: q,
        type: "line",
        data: vals,
        symbol: "none",
        lineStyle: { color: Q_COLORS[i], width: isLeg ? 2 : 1.2, opacity: isLeg ? 1 : 0.6 },
        itemStyle: { color: Q_COLORS[i] },
        z: isLeg ? 5 : 3,
      });
    });

    series.push({
      name: lsLabel,
      type: "line",
      data: data.long_short,
      symbol: "none",
      lineStyle: { color: LS_COLOR, width: 2.5, type: "dashed" },
      itemStyle: { color: LS_COLOR },
      z: 6,
    });

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: [...quintiles, lsLabel],
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0,
        itemWidth: 18,
        itemHeight: 8,
      },
      grid: { left: 52, right: 10, top: 32, bottom: 28 },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: t.textColor, hideOverlap: true, formatter: (v: string) => v.slice(0, 7) },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { fontSize: 10, color: t.textColor, formatter: (v: number) => v.toFixed(2) },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        valueFormatter: (v: number) => v?.toFixed(4) ?? "",
      },
      series,
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [data, dark]);

  return <div ref={ref} style={{ height }} />;
}
