import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import type { TopicStat } from "@/lib/learning/stats";

/** 五主题掌握度雷达图 */
export function MasteryRadar({ stats, height = 280 }: { stats: TopicStat[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current) return;
    const t = getChartTheme();
    const primary = getComputedStyle(document.documentElement).getPropertyValue("--primary").trim();
    const primaryColor = primary ? `hsl(${primary})` : "#2f6f6a";

    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 500,
      tooltip: {
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
      },
      radar: {
        indicator: stats.map((s) => ({ name: s.title, max: 100 })),
        radius: "68%",
        center: ["50%", "54%"],
        axisName: { color: t.textColor, fontSize: 11 },
        splitLine: { lineStyle: { color: t.gridColor } },
        splitArea: { areaStyle: { color: ["transparent"] } },
        axisLine: { lineStyle: { color: t.gridColor } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: stats.map((s) => s.mastery),
              name: "掌握度",
              areaStyle: { color: primaryColor, opacity: 0.18 },
              lineStyle: { color: primaryColor, width: 2 },
              itemStyle: { color: primaryColor },
              symbolSize: 4,
            },
          ],
        },
      ],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [stats, dark]);

  return <div ref={ref} style={{ height }} />;
}
