import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { ForecastResponse, TradeSignal } from "@/lib/api";

interface Props {
  data: ForecastResponse;
  height?: number;
  trades?: TradeSignal[];
}

// Build a future-aligned series: nulls across history, a junction anchor at the
// last historical date (so lines visually connect), then the forecast values.
function futureAligned(nHist: number, junction: number, values: number[]): (number | null)[] {
  const head = new Array(Math.max(nHist - 1, 0)).fill(null) as (number | null)[];
  return [...head, junction, ...values];
}

export function ForecastChart({ data, height = 320, trades }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();
    const hist = data.history.filter((b) => b.close != null && isFinite(b.close));
    if (hist.length < 2) return;

    const histDates = hist.map((b) => b.date);
    const histCloses = hist.map((b) => b.close);
    const nHist = histDates.length;
    const lastClose = histCloses[nHist - 1];
    const allDates = [...histDates, ...data.future_dates];

    const histSeries = [...histCloses, ...new Array(data.future_dates.length).fill(null)];

    const series: any[] = [
      {
        name: "历史价格",
        type: "line",
        data: histSeries,
        symbol: "none",
        lineStyle: { color: t.textColor, width: 1.5 },
        z: 5,
      },
    ];

    // Cone (p10–p90) via two stacked area series — only when the model ran.
    if (data.model) {
      const { p10, p50, p90 } = data.model;
      const band = p90.map((v, i) => v - p10[i]);
      series.push(
        {
          name: "_p10",
          type: "line",
          data: futureAligned(nHist, lastClose, p10),
          stack: "cone",
          symbol: "none",
          lineStyle: { opacity: 0 },
          silent: true,
          z: 1,
        },
        {
          name: "80% 区间",
          type: "line",
          data: futureAligned(nHist, 0, band),
          stack: "cone",
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { color: t.upColor, opacity: 0.14 },
          z: 1,
        },
        {
          name: "TimesFM 中位",
          type: "line",
          data: futureAligned(nHist, lastClose, p50),
          symbol: "none",
          lineStyle: { color: t.upColor, width: 1.6, type: "dashed" },
          z: 4,
        },
      );
    }

    // Naive baselines.
    series.push(
      {
        name: "随机游走",
        type: "line",
        data: futureAligned(nHist, lastClose, data.baselines.random_walk),
        symbol: "none",
        lineStyle: { color: t.textColor, width: 1, type: "dotted", opacity: 0.55 },
        z: 3,
      },
      {
        name: "趋势外推",
        type: "line",
        data: futureAligned(nHist, lastClose, data.baselines.drift),
        symbol: "none",
        lineStyle: { color: "#f59e0b", width: 1, type: "dotted", opacity: 0.7 },
        z: 3,
      },
    );

    // Trade signal markers (entry ▲ / exit ▼) + holding shading
    const dateIdx = new Map(allDates.map((d, i) => [d, i]));
    const legendNames = ["历史价格", "TimesFM 中位", "80% 区间", "随机游走", "趋势外推"];
    if (trades && trades.length > 0) {
      const entryData: any[] = [];
      const exitData: any[] = [];
      const markAreas: any[] = [];
      for (const tr of trades) {
        const ei = dateIdx.get(tr.entry_date);
        const xi = dateIdx.get(tr.exit_date);
        if (ei != null) {
          entryData.push([tr.entry_date, tr.entry_price]);
        }
        if (xi != null) {
          exitData.push([tr.exit_date, tr.exit_price]);
        }
        // Shading: use entry or chart start, exit or chart end
        const areaStart = ei != null ? tr.entry_date : (xi != null ? allDates[0] : null);
        const areaEnd = xi != null ? tr.exit_date : (ei != null ? histDates[nHist - 1] : null);
        if (areaStart && areaEnd) {
          markAreas.push([{ xAxis: areaStart }, { xAxis: areaEnd }]);
        }
      }
      series.push(
        {
          name: "开仓",
          type: "scatter",
          data: entryData,
          symbol: "triangle",
          symbolSize: 12,
          itemStyle: { color: "#10b981" },
          z: 10,
        },
        {
          name: "平仓",
          type: "scatter",
          data: exitData,
          symbol: "triangle",
          symbolSize: 12,
          symbolRotate: 180,
          itemStyle: { color: "#ef4444" },
          z: 10,
        },
      );
      if (markAreas.length > 0) {
        series[0] = {
          ...series[0],
          markArea: {
            silent: true,
            itemStyle: { color: "rgba(16, 185, 129, 0.06)" },
            data: markAreas,
          },
        };
      }
      legendNames.push("开仓", "平仓");
    }

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: legendNames,
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0,
        itemWidth: 18,
        itemHeight: 8,
      },
      grid: { left: 52, right: 10, top: 30, bottom: 28 },
      xAxis: {
        type: "category",
        data: allDates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: {
          fontSize: 10,
          color: t.textColor,
          hideOverlap: true,
          formatter: (val: string) => val.slice(0, 7),
        },
      },
      yAxis: (() => {
        const vals = histCloses.filter(v => v != null && isFinite(v));
        if (data.model) { vals.push(...data.model.p10, ...data.model.p90); }
        vals.push(...data.baselines.random_walk, ...data.baselines.drift);
        const lo = Math.min(...vals);
        const hi = Math.max(...vals);
        const pad = (hi - lo) * 0.05;
        return {
          type: "value",
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { fontSize: 10, color: t.textColor },
          axisLine: { show: false },
          axisTick: { show: false },
          min: Math.floor((lo - pad) * 100) / 100,
          max: Math.ceil((hi + pad) * 100) / 100,
        };
      })(),
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
      },
      series: [
        // Vertical divider at "today" attached to the history series via markLine.
        ...series.map((s, i) =>
          i === 0
            ? {
                ...s,
                markLine: {
                  symbol: "none",
                  silent: true,
                  lineStyle: { color: t.axisColor, type: "solid", opacity: 0.5 },
                  label: { show: true, formatter: "今", color: t.textColor, fontSize: 10 },
                  data: [{ xAxis: histDates[nHist - 1] }],
                },
              }
            : s,
        ),
      ],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [data, dark, trades]);

  return <div ref={ref} style={{ height }} />;
}
