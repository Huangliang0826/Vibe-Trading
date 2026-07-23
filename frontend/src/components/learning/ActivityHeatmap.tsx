import { useMemo } from "react";
import type { HeatCell } from "@/lib/learning/stats";

/** GitHub 式学习热力日历(CSS 网格实现,轻量且主题自适应) */
export function ActivityHeatmap({ cells }: { cells: HeatCell[] }) {
  // 按周分列:每列 7 天(周日→周六)。首列补齐到周首。
  const { columns, monthLabels } = useMemo(() => {
    const padded: (HeatCell | null)[] = [...cells];
    if (padded.length > 0) {
      const firstDow = new Date(cells[0].date + "T00:00:00").getDay();
      for (let i = 0; i < firstDow; i++) padded.unshift(null);
    }
    const cols: (HeatCell | null)[][] = [];
    for (let i = 0; i < padded.length; i += 7) cols.push(padded.slice(i, i + 7));

    // 月份标签:某列第一个非空格子的月份与上一列不同则标注
    const labels: { col: number; text: string }[] = [];
    let lastMonth = -1;
    cols.forEach((col, ci) => {
      const firstCell = col.find((c) => c);
      if (!firstCell) return;
      const m = new Date(firstCell.date + "T00:00:00").getMonth();
      if (m !== lastMonth) {
        labels.push({ col: ci, text: `${m + 1}月` });
        lastMonth = m;
      }
    });
    return { columns: cols, monthLabels: labels };
  }, [cells]);

  const level = (count: number) => {
    if (count <= 0) return 0;
    if (count <= 2) return 1;
    if (count <= 5) return 2;
    if (count <= 9) return 3;
    return 4;
  };

  const levelClass = [
    "bg-muted/60",
    "bg-primary/25",
    "bg-primary/45",
    "bg-primary/70",
    "bg-primary",
  ];

  return (
    <div className="overflow-x-auto">
      <div className="inline-flex flex-col gap-1">
        {/* 月份标签行 */}
        <div className="flex gap-1 pl-0 text-[9px] text-muted-foreground">
          {columns.map((_, ci) => {
            const label = monthLabels.find((l) => l.col === ci);
            return (
              <div key={ci} className="w-2.5 shrink-0">
                {label ? <span className="relative -left-0.5 whitespace-nowrap">{label.text}</span> : null}
              </div>
            );
          })}
        </div>
        {/* 热力网格 */}
        <div className="flex gap-1">
          {columns.map((col, ci) => (
            <div key={ci} className="flex flex-col gap-1">
              {Array.from({ length: 7 }).map((_, ri) => {
                const cell = col[ri];
                if (!cell) return <div key={ri} className="h-2.5 w-2.5" />;
                return (
                  <div
                    key={ri}
                    className={`h-2.5 w-2.5 rounded-[3px] ${levelClass[level(cell.count)]}`}
                    title={`${cell.date}:${cell.count > 0 ? `${cell.count} 次学习` : "无活动"}`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <span>少</span>
        {levelClass.map((c, i) => (
          <span key={i} className={`h-2.5 w-2.5 rounded-[3px] ${c}`} />
        ))}
        <span>多</span>
      </div>
    </div>
  );
}
