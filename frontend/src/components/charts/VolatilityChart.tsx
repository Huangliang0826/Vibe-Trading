import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { VolatilityResponse } from "@/lib/api";

interface Props {
  data: VolatilityResponse;
  height?: number;
}

function pctTick(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

export function VolatilityChart({ data, height = 220 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();

    const hasHistory = Array.isArray(data.history_vol) && data.history_vol.length > 0;
    const hasForecast = data.forecast != null;

    if (!hasHistory && !hasForecast) return;

    const nHist = hasHistory ? data.history_vol!.length : 0;
    const nFcst = hasForecast ? data.forecast!.point.length : 0;

    // Build date-like indices: history + forecast steps
    const histLabels = hasHistory
      ? data.history_vol!.map((_, i) => `-${nHist - i}`).reverse()
      : [];
    const fcstLabels = hasForecast
      ? data.forecast!.point.map((_, i) => `+${i + 1}`)
      : [];
    const allLabels = [...histLabels, ...fcstLabels];

    const series: any[] = [];

    // Historical realised vol line
    if (hasHistory) {
      const dataWithNulls = [...data.history_vol!, ...new Array(nFcst).fill(null)];
      series.push({
        name: "历史波动率",
        type: "line",
        data: dataWithNulls,
        symbol: "none",
        lineStyle: { color: t.infoColor, width: 1.2, opacity: 0.7 },
        z: 5,
      });
    }

    // Forecast cone (p10–p90 shaded) + p50 line
    if (hasForecast) {
      const f = data.forecast!;
      const nulls = new Array(nHist).fill(null);
      const band = f.p90.map((v, i) => v - f.p10[i]);

      series.push(
        {
          name: "_p10",
          type: "line",
          data: [...nulls, ...f.p10],
          stack: "vol_cone",
          symbol: "none",
          lineStyle: { opacity: 0 },
          silent: true,
          z: 1,
        },
        {
          name: "80% 置信区间",
          type: "line",
          data: [...nulls, ...band],
          stack: "vol_cone",
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { color: t.warningColor, opacity: 0.15 },
          z: 1,
        },
        {
          name: "预测中位波动率",
          type: "line",
          data: [...nulls, ...f.p50],
          symbol: "none",
          lineStyle: { color: t.warningColor, width: 1.6, type: "dashed" },
          z: 4,
        },
      );
    }

    // Median vol horizontal reference line
    const medianVol = data.regime?.median_vol;
    if (medianVol != null) {
      series.push({
        name: "历史中位波动率",
        type: "line",
        data: [
          [allLabels[0], medianVol],
          [allLabels[allLabels.length - 1], medianVol],
        ],
        symbol: "none",
        lineStyle: { color: t.textColor, width: 1, type: "dotted", opacity: 0.5 },
        z: 2,
      });
    }

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: ["历史波动率", "80% 置信区间", "预测中位波动率", "历史中位波动率"].filter(
          (name) => series.some((s) => s.name === name),
        ),
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0,
        itemWidth: 18,
        itemHeight: 8,
      },
      grid: { left: 52, right: 16, top: 30, bottom: 28 },
      xAxis: {
        type: "category",
        data: allLabels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: t.textColor, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: {
          fontSize: 10,
          color: t.textColor,
          formatter: (v: number) => pctTick(v),
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        valueFormatter: (v: number | null) => (v != null ? pctTick(v) : "—"),
      },
      series,
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [data, dark]);

  return <div ref={ref} style={{ height }} />;
}
