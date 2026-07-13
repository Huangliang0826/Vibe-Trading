import type { AnalyticsCoverage, AnalyticsFreshness } from "@/lib/api";
import { cn } from "@/lib/utils";

const REASONS: Record<string, string> = {
  no_persisted_forecast_history: "暂无可回填的 Forecast 历史；新结果将从现在开始积累。",
  no_local_records: "本地暂时没有可用历史记录。",
  parse_errors: "部分历史文件无法读取，已展示其余可用数据。",
  source_read_failed: "本地历史来源暂时无法读取。",
};

const FRESHNESS_LABELS: Record<AnalyticsFreshness, string> = {
  fresh: "数据新鲜",
  stale: "数据可能已过期",
  no_data: "等待数据",
};

export function DataCoverageSummary({
  freshness,
  coverage,
}: {
  freshness: AnalyticsFreshness;
  coverage: AnalyticsCoverage;
}) {
  const dataThroughCandidates = coverage.sources
    .map((source) => source.data_through)
    .filter((value): value is string => Boolean(value))
    .sort();
  const dataThrough = dataThroughCandidates[dataThroughCandidates.length - 1];
  const reasons = [...new Set(
    coverage.sources
      .map((source) => source.reason)
      .filter((reason): reason is string => Boolean(reason)),
  )];

  return (
    <aside
      className={cn(
        "rounded-xl border px-4 py-3 text-xs",
        freshness === "fresh" && "bg-card text-muted-foreground",
        freshness === "stale" && "border-amber-500/30 bg-amber-500/10 text-amber-700",
        freshness === "no_data" && "border-dashed bg-muted/20 text-muted-foreground",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-medium text-foreground">
          覆盖 {coverage.covered_days} / {coverage.window_days} 天
        </span>
        <span>{FRESHNESS_LABELS[freshness]}</span>
        {dataThrough && <span>数据截至 {dataThrough}</span>}
      </div>
      {reasons.map((reason) => (
        <p key={reason} className="mt-2">
          {REASONS[reason] || `数据来源提示：${reason}`}
        </p>
      ))}
    </aside>
  );
}
