import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { StrategyResponse } from "@/lib/api";

interface Props {
  data: StrategyResponse;
  height?: number;
}

/** Strategy equity curves vs buy-and-hold and DCA baselines. */
export function StrategyEquityChart({ data, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current || !data.strategies || !data.buy_and_hold) return;
    const t = getChartTheme();
    const bh = data.buy_and_hold.equity;
    const dca = data.dca?.equity;
    const dates = bh.map((p) => p[0]);
    const line = (
      name: string, eq: [string, number][], color: string, width: number, dash?: boolean,
    ) => ({
      name, type: "line", data: eq.map((p) => p[1]), symbol: "none",
      lineStyle: { color, width, ...(dash ? { type: "dashed" } : {}) },
    });

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: ["区间均值回归", "中位线趋势", "风控叠加", "买入持有", ...(dca ? ["定投"] : [])],
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0, itemWidth: 18, itemHeight: 8,
      },
      grid: { left: 56, right: 10, top: 28, bottom: 26 },
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: t.textColor, hideOverlap: true, formatter: (v: string) => v.slice(0, 7) },
      },
      yAxis: {
        type: "value", scale: true,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { fontSize: 10, color: t.textColor },
        axisLine: { show: false }, axisTick: { show: false },
      },
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, borderColor: t.tooltipBorder, textStyle: { color: t.tooltipText, fontSize: 11 } },
      series: [
        line("区间均值回归", data.strategies.band_reversion.equity, t.infoColor, 1.6),
        line("中位线趋势", data.strategies.median_trend.equity, "#f59e0b", 1.3, true),
        line("风控叠加", data.strategies.vol_target.equity, t.upColor, 1.6),
        line("买入持有", bh, t.textColor, 1.6),
        ...(dca ? [line("定投", dca, "#8b5cf6", 1.6, true)] : []),
      ],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [data, dark]);

  return <div ref={ref} style={{ height }} />;
}
