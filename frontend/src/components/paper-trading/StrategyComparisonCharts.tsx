import { useEffect, useRef } from "react";

import { useDarkMode } from "@/hooks/useDarkMode";
import type { StrategyComparisonResult } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";

type PointField = "normalized" | "drawdown" | "cash_ratio";

export function comparisonChartSeries(results: StrategyComparisonResult[], field: PointField) {
  return results
    .filter((result) => result.status === "completed" && result.points.length > 0)
    .map((result) => ({
      name: result.label,
      data: result.points.map((point) => [point.date, point[field]] as [string, number]),
    }));
}

interface LineChartProps {
  title: string;
  results: StrategyComparisonResult[];
  field: PointField;
  percent?: boolean;
}

function ComparisonLineChart({ title, results, field, percent = false }: LineChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const theme = getChartTheme();
    const colors = [theme.infoColor, theme.warningColor, theme.upColor];
    const series = comparisonChartSeries(results, field);
    chart.setOption({
      animationDuration: 250,
      color: colors,
      legend: { top: 0, textStyle: { color: theme.textColor, fontSize: 10 } },
      grid: { left: 54, right: 16, top: 40, bottom: 34 },
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        valueFormatter: (value: number) => percent ? `${(value * 100).toFixed(1)}%` : Number(value).toFixed(2),
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: theme.axisColor } },
        axisLabel: { color: theme.textColor, fontSize: 10 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: field === "normalized",
        axisLabel: {
          color: theme.textColor,
          fontSize: 10,
          formatter: (value: number) => percent ? `${(value * 100).toFixed(0)}%` : value.toFixed(1),
        },
        splitLine: { lineStyle: { color: theme.gridColor } },
      },
      series: series.map((item) => ({
        ...item,
        type: "line",
        showSymbol: false,
        sampling: "lttb",
        lineStyle: { width: 2 },
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [dark, field, percent, results]);

  return (
    <section className="rounded-xl border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <div ref={ref} className="h-64" aria-label={title} />
    </section>
  );
}

function AnnualReturnsChart({ results }: { results: StrategyComparisonResult[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const completed = results.filter((result) => result.status === "completed" && result.metrics);
    const years = [...new Set(completed.flatMap((result) => Object.keys(result.metrics?.annual_returns ?? {})))].sort();
    const chart = echarts.init(ref.current);
    const theme = getChartTheme();
    chart.setOption({
      animationDuration: 250,
      color: [theme.infoColor, theme.warningColor, theme.upColor],
      legend: { top: 0, textStyle: { color: theme.textColor, fontSize: 10 } },
      grid: { left: 54, right: 16, top: 40, bottom: 34 },
      tooltip: { trigger: "axis", valueFormatter: (value: number) => `${(value * 100).toFixed(1)}%` },
      xAxis: { type: "category", data: years, axisLabel: { color: theme.textColor }, axisLine: { lineStyle: { color: theme.axisColor } } },
      yAxis: {
        type: "value",
        axisLabel: { color: theme.textColor, formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: theme.gridColor } },
      },
      series: completed.map((result) => ({
        name: result.label,
        type: "bar",
        data: years.map((year) => result.metrics?.annual_returns[year] ?? null),
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [dark, results]);

  return (
    <section className="rounded-xl border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold">年度收益</h3>
      <div ref={ref} className="h-64" aria-label="年度收益" />
    </section>
  );
}

export function StrategyComparisonCharts({ results }: { results: StrategyComparisonResult[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ComparisonLineChart title="累计净值趋势" results={results} field="normalized" />
      <ComparisonLineChart title="回撤趋势" results={results} field="drawdown" percent />
      <ComparisonLineChart title="现金比例趋势" results={results} field="cash_ratio" percent />
      <AnnualReturnsChart results={results} />
    </div>
  );
}
