import { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, Database, RefreshCw } from "lucide-react";
import { api, type AnalyticsDays, type AnalyticsMetricPoint, type AnalyticsSystemHealthResponse, type AnalyticsUsageResponse } from "@/lib/api";
import { MetricCard } from "@/components/analytics/MetricCard";
import { TrendChart } from "@/components/analytics/TrendChart";
import { cn } from "@/lib/utils";
import { ResearchQualityView } from "@/components/analytics/ResearchQualityView";
import { DevelopmentView } from "@/components/analytics/DevelopmentView";
import { DataCoverageSummary } from "@/components/analytics/DataCoverageSummary";

type AnalyticsView = "usage" | "system" | "research" | "development";
type DashboardResponse = AnalyticsUsageResponse | AnalyticsSystemHealthResponse;

const LABELS: Record<string, string> = {
  effective_research_sessions: "有效研究会话",
  task_success_rate: "任务成功率",
  result_view_rate: "结果查看率",
  time_to_insight_p95_ms: "P95 洞察时间",
  duration_p95_ms: "P95 延迟",
  request_success_rate: "请求成功率",
  freshness_compliance_rate: "数据新鲜度达标率",
  completeness_rate: "数据完整率",
};

const VIEW_METRICS: Record<AnalyticsView, string[]> = {
  usage: ["effective_research_sessions", "task_success_rate", "result_view_rate", "time_to_insight_p95_ms"],
  system: ["duration_p95_ms", "request_success_rate", "freshness_compliance_rate", "completeness_rate"],
  research: [],
  development: [],
};

function dailyValues(points: AnalyticsMetricPoint[], metric: string): Array<{ bucket: string; value: number }> {
  const grouped = new Map<string, AnalyticsMetricPoint[]>();
  for (const point of points.filter((row) => row.metric === metric && row.value != null)) {
    grouped.set(point.bucket, [...(grouped.get(point.bucket) || []), point]);
  }
  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([bucket, rows]) => {
    const denominator = rows.reduce((sum, row) => sum + Number(row.denominator || 0), 0);
    const numerator = rows.reduce((sum, row) => sum + Number(row.numerator || 0), 0);
    const isRate = rows.some((row) => row.denominator != null);
    return {
      bucket,
      value: isRate && denominator > 0
        ? numerator / denominator
        : rows.reduce((sum, row) => sum + Number(row.value), 0),
    };
  });
}

function formatValue(metric: string, value: number | null): string {
  if (value == null) return "暂无";
  if (metric.includes("rate") || metric.includes("compliance")) return `${(value * 100).toFixed(1)}%`;
  if (metric.endsWith("_ms")) return value >= 1_000 ? `${(value / 1_000).toFixed(1)}s` : `${Math.round(value)}ms`;
  return Math.round(value).toLocaleString();
}

export function Analytics() {
  const [view, setView] = useState<AnalyticsView>("usage");
  const [days, setDays] = useState<AnalyticsDays>(30);
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (view === "research" || view === "development") {
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const request = view === "usage" ? api.getAnalyticsUsage(days) : api.getAnalyticsSystemHealth(days);
    request.then((response) => {
      if (!cancelled) setData(response);
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "加载分析数据失败");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [days, view]);

  const metrics = VIEW_METRICS[view];
  const series = useMemo(() => Object.fromEntries(metrics.map((metric) => [metric, dailyValues(data?.points || [], metric)])), [data, metrics]);
  const noData = view !== "research" && view !== "development" && !loading && (data?.warnings.includes("no_data") || !data?.points.length);

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2"><BarChart3 className="h-6 w-6 text-primary" /><h1 className="text-2xl font-semibold">数据洞察</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">本地统计功能使用、研究效率和系统稳定性趋势</p>
        </div>
        <div className="flex gap-1 rounded-lg border bg-muted/30 p-1">
          {[7, 30, 90].map((value) => <button key={value} onClick={() => setDays(value as AnalyticsDays)} className={cn("rounded-md px-3 py-1.5 text-xs", days === value ? "bg-background text-foreground shadow-sm" : "text-muted-foreground")}>{value} 天</button>)}
        </div>
      </header>

      <div className="flex gap-2">
        <button onClick={() => setView("usage")} className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", view === "usage" && "border-primary bg-primary/10 text-primary")}><Activity className="h-4 w-4" />功能使用</button>
        <button onClick={() => setView("system")} className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", view === "system" && "border-primary bg-primary/10 text-primary")}><Database className="h-4 w-4" />系统健康</button>
        <button onClick={() => setView("research")} className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", view === "research" && "border-primary bg-primary/10 text-primary")}><BarChart3 className="h-4 w-4" />研究质量</button>
        <button onClick={() => setView("development")} className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", view === "development" && "border-primary bg-primary/10 text-primary")}><RefreshCw className="h-4 w-4" />研发与版本</button>
      </div>

      {view === "research" && <ResearchQualityView days={days} />}
      {view === "development" && <DevelopmentView days={days} />}

      {loading && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[1, 2, 3, 4].map((item) => <div key={item} className="h-28 animate-pulse rounded-xl bg-muted" />)}</div>}
      {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-500">{error}</div>}
      {view !== "research" && view !== "development" && !loading && !error && data && <DataCoverageSummary freshness={data.freshness} coverage={data.coverage} />}
      {noData && <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">暂无统计数据。使用功能后，趋势将在下一次本地聚合时显示。</div>}

      {view !== "research" && view !== "development" && !loading && !error && !noData && data && (
        <>
          {data.warnings.length > 0 && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">数据提示：{data.warnings.join("、")}</div>}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {metrics.map((metric) => {
              const values = series[metric] || [];
              const current = values[values.length - 1]?.value ?? null;
              const previous = values[values.length - 2]?.value ?? null;
              const delta = current != null && previous != null && previous !== 0 ? ((current - previous) / Math.abs(previous)) * 100 : null;
              return <MetricCard key={metric} label={LABELS[metric]} value={formatValue(metric, current)} delta={delta} sparkline={values.map((row) => row.value)} detail={`样本 ${data.sample_count.toLocaleString()}`} />;
            })}
          </div>
          <TrendChart title={view === "usage" ? "研究会话趋势" : "系统延迟趋势"} points={data.points} metric={view === "usage" ? "effective_research_sessions" : "duration_p95_ms"} />
          {view === "usage" && "funnel" in data && data.funnel.length > 0 && <section className="rounded-xl border bg-card p-4"><h2 className="text-sm font-semibold">研究会话漏斗</h2><div className="mt-3 grid gap-2 sm:grid-cols-5">{data.funnel.map((step) => <div key={step.step} className="rounded-lg bg-muted/40 p-3"><p className="text-xs text-muted-foreground">{step.step}</p><p className="mt-1 font-semibold">{step.rate == null ? "暂无" : `${(step.rate * 100).toFixed(1)}%`}</p><p className="text-[10px] text-muted-foreground">{step.numerator}/{step.denominator}</p></div>)}</div></section>}
          <footer className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground"><span>数据截至 {data.data_through || "暂无"}</span><span>样本 {data.sample_count.toLocaleString()}</span><span>{data.calculation_version}</span><RefreshCw className="h-3 w-3" /></footer>
        </>
      )}
    </div>
  );
}
