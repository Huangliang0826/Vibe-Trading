import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { CalibrationResponse } from "@/lib/api";

interface Props {
  overlay: NonNullable<CalibrationResponse["overlay"]>;
  height?: number;
}

function futureAligned(nCtx: number, junction: number, values: number[]): (number | null)[] {
  const head = new Array(Math.max(nCtx - 1, 0)).fill(null) as (number | null)[];
  return [...head, junction, ...values];
}

/** Predicted cone vs what actually happened, for the most recent backtest fold. */
export function CalibrationChart({ overlay, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();
    const nCtx = overlay.context.length;
    if (nCtx < 1) return;
    const last = overlay.context[nCtx - 1];
    const allDates = [...overlay.context_dates, ...overlay.future_dates];
    const band = overlay.p90.map((v, i) => v - overlay.p10[i]);
    const q = overlay.q ?? 0;
    const hasConf = !!overlay.q;
    const confLegend = hasConf ? ["共形区间"] : [];

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: ["历史", "实际走势", "预测中位", "80% 区间", ...confLegend],
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0, itemWidth: 18, itemHeight: 8,
      },
      grid: { left: 50, right: 10, top: 30, bottom: 26 },
      xAxis: {
        type: "category", data: allDates, boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: t.textColor, hideOverlap: true, formatter: (v: string) => v.slice(5) },
      },
      yAxis: {
        type: "value", scale: true,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { fontSize: 10, color: t.textColor },
        axisLine: { show: false }, axisTick: { show: false },
      },
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, borderColor: t.tooltipBorder, textStyle: { color: t.tooltipText, fontSize: 11 } },
      series: [
        {
          name: "历史", type: "line",
          data: [...overlay.context, ...new Array(overlay.future_dates.length).fill(null)],
          symbol: "none", lineStyle: { color: t.textColor, width: 1.3 }, z: 4,
        },
        {
          name: "实际走势", type: "line",
          data: futureAligned(nCtx, last, overlay.realized),
          symbol: "none", lineStyle: { color: t.upColor, width: 1.8 }, z: 5,
        },
        {
          name: "_p10", type: "line", data: futureAligned(nCtx, last, overlay.p10),
          stack: "c", symbol: "none", lineStyle: { opacity: 0 }, silent: true, z: 1,
        },
        {
          name: "80% 区间", type: "line", data: futureAligned(nCtx, 0, band),
          stack: "c", symbol: "none", lineStyle: { opacity: 0 },
          areaStyle: { color: t.infoColor, opacity: 0.14 }, z: 1,
        },
        {
          name: "预测中位", type: "line", data: futureAligned(nCtx, last, overlay.p50),
          symbol: "none", lineStyle: { color: t.infoColor, width: 1.4, type: "dashed" }, z: 3,
        },
        // Conformal band edges (p10 - q, p90 + q) as dashed boundaries.
        ...(hasConf ? [
          {
            name: "共形区间", type: "line",
            data: futureAligned(nCtx, last, overlay.p90.map((v) => v + q)),
            symbol: "none", lineStyle: { color: t.warningColor, width: 1, type: "dashed" }, z: 2,
          },
          {
            name: "共形区间", type: "line",
            data: futureAligned(nCtx, last, overlay.p10.map((v) => v - q)),
            symbol: "none", lineStyle: { color: t.warningColor, width: 1, type: "dashed" }, z: 2,
          },
        ] : []),
      ],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [overlay, dark]);

  return <div ref={ref} style={{ height }} />;
}
