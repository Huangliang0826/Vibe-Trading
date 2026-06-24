import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { SmartTResponse } from "@/lib/api";

interface Props {
  data: SmartTResponse;
  height?: number;
}

export function SmartTChart({ data, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();
    const dates = data.smart_t.equity.map((p) => p[0]);
    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      legend: {
        data: ["智能做T", "买入持有"],
        textStyle: { color: t.textColor, fontSize: 10 },
        top: 0,
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
        scale: true,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { fontSize: 10, color: t.textColor, formatter: (v: number) => v.toFixed(2) },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        valueFormatter: (v: number) => v?.toFixed(4) ?? "",
      },
      series: [
        {
          name: "智能做T",
          type: "line",
          data: data.smart_t.equity.map((p) => p[1]),
          symbol: "none",
          lineStyle: { color: t.upColor, width: 2.2 },
        },
        {
          name: "买入持有",
          type: "line",
          data: data.buy_and_hold.equity.map((p) => p[1]),
          symbol: "none",
          lineStyle: { color: t.textColor, width: 1.4, type: "dashed" },
        },
      ],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [data, dark]);

  return <div ref={ref} style={{ height }} />;
}
