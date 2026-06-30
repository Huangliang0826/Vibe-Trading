import { useEffect, useRef } from "react";
import type { OpportunityHistoryPoint } from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";

export function OpportunityHistoryChart({ points, height = 160 }: { points: OpportunityHistoryPoint[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current || points.length === 0) return;
    const theme = getChartTheme();
    const chart = echarts.init(ref.current);
    const ordered = [...points].reverse();
    chart.setOption({
      animation: false,
      grid: { left: 34, right: 12, top: 12, bottom: 24 },
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: Array<{ data: { value: number | null; level: string }; axisValue: string }>) => {
          const row = params[0];
          return `${row.axisValue}<br/>评分 ${row.data.value?.toFixed(1) ?? "—"}<br/>${row.data.level}`;
        },
      },
      xAxis: {
        type: "category",
        data: ordered.map((point) => point.snapshot_date),
        axisLine: { lineStyle: { color: theme.axisColor } },
        axisLabel: { color: theme.textColor, fontSize: 9, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        interval: 25,
        axisLabel: { color: theme.textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: theme.gridColor } },
      },
      series: [{
        type: "line",
        symbol: "circle",
        symbolSize: 4,
        smooth: false,
        lineStyle: { color: theme.textColor, width: 1.5 },
        itemStyle: { color: theme.textColor },
        data: ordered.map((point) => ({ value: point.score, level: point.level })),
        markLine: {
          symbol: "none",
          silent: true,
          label: { show: false },
          lineStyle: { type: "dashed", color: theme.gridColor, width: 1 },
          data: [{ yAxis: 55 }, { yAxis: 75 }],
        },
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [points, dark]);

  if (!points.length) return <p className="text-xs text-muted-foreground">暂无历史评分</p>;
  return <div ref={ref} style={{ height }} className="w-full" aria-label="机会评分历史" />;
}
