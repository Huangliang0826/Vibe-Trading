import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { AnalyticsMetricPoint } from "@/lib/api";

interface TrendChartProps {
  title: string;
  points: AnalyticsMetricPoint[];
  metric: string;
  height?: number;
}

export function TrendChart({ title, points, metric, height = 300 }: TrendChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const theme = getChartTheme();
    const selected = points.filter((point) => point.metric === metric);
    const buckets = [...new Set(selected.map((point) => point.bucket))].sort();
    const values = buckets.map((bucket) => {
      const rows = selected.filter((point) => point.bucket === bucket && point.value != null);
      if (!rows.length) return null;
      return rows.reduce((sum, point) => sum + Number(point.value), 0);
    });
    const samples = buckets.map((bucket) =>
      selected.filter((point) => point.bucket === bucket).reduce((sum, point) => sum + point.sample_count, 0)
    );
    chart.setOption({
      animationDuration: 250,
      grid: { left: 48, right: 18, top: 24, bottom: 34 },
      tooltip: {
        trigger: "axis",
        formatter: (params: Array<{ dataIndex: number; value: number | null }>) => {
          const first = params[0];
          if (!first) return "";
          return `${buckets[first.dataIndex]}<br/>${first.value ?? "暂无"}<br/>样本 ${samples[first.dataIndex]}`;
        },
      },
      xAxis: { type: "category", data: buckets, axisLabel: { color: theme.axisColor } },
      yAxis: { type: "value", scale: true, axisLabel: { color: theme.axisColor }, splitLine: { lineStyle: { color: theme.gridColor } } },
      series: [{ type: "line", data: values, smooth: true, connectNulls: false, symbolSize: 6, lineStyle: { width: 2, color: theme.upColor }, itemStyle: { color: theme.upColor }, areaStyle: { color: theme.upColor, opacity: 0.08 } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dark, metric, points]);

  return (
    <section className="rounded-xl border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      <div ref={ref} style={{ height }} aria-label={title} />
    </section>
  );
}
