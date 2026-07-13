import { useEffect, useMemo, useState } from "react";
import { api, type AnalyticsDays, type AnalyticsResearchQualityParams, type AnalyticsResearchQualityResponse } from "@/lib/api";
import { TrendChart } from "@/components/analytics/TrendChart";
import { DataCoverageSummary } from "@/components/analytics/DataCoverageSummary";
import { cn } from "@/lib/utils";

type Subject = AnalyticsResearchQualityParams["subject"];

const SUBJECTS: Array<{ value: Subject; label: string }> = [
  { value: "scanner", label: "Scanner" },
  { value: "forecast", label: "Forecast" },
  { value: "backtest", label: "Backtest" },
  { value: "paper_trading", label: "Paper Trading" },
];

function percentMetric(metric: string): boolean {
  return metric.includes("accuracy") || metric.includes("rate") || metric.includes("coverage");
}

function formatMetric(metric: string, value: number | null): string {
  if (value == null) return "暂无";
  return percentMetric(metric) ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
}

export function ResearchQualityView({ days }: { days: AnalyticsDays }) {
  const [subject, setSubject] = useState<Subject>("scanner");
  const [market, setMarket] = useState("us");
  const [horizon, setHorizon] = useState("5d");
  const [data, setData] = useState<AnalyticsResearchQualityResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const selectedHorizon = subject === "forecast" && horizon === "5d" ? "63d" : horizon;
    api.getAnalyticsResearchQuality({ days, subject, market, horizon: selectedHorizon, regime: "all" })
      .then((response) => { if (!cancelled) setData(response); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days, horizon, market, subject]);

  const primary = data?.series.find((point) => point.value != null) || data?.series[0];
  const trendPoints = useMemo(() => (data?.series || []).map((point) => ({
    bucket: point.bucket,
    metric: point.metric,
    dimensions: { subject: point.subject, market: point.market, horizon: point.horizon },
    value: point.value,
    sample_count: point.sample_count,
    interval_low: point.interval_low,
    interval_high: point.interval_high,
  })), [data]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {SUBJECTS.map((item) => <button key={item.value} onClick={() => setSubject(item.value)} className={cn("rounded-lg border px-3 py-2 text-sm", subject === item.value && "border-primary bg-primary/10 text-primary")}>{item.label}</button>)}
      </div>
      <div className="flex flex-wrap gap-3 rounded-xl border bg-card p-3">
        <label className="text-xs text-muted-foreground">市场<select aria-label="市场" value={market} onChange={(event) => setMarket(event.target.value)} className="ml-2 rounded border bg-background px-2 py-1"><option value="us">美股</option><option value="hk">港股</option><option value="cn">A股</option></select></label>
        <label className="text-xs text-muted-foreground">周期<select aria-label="周期" value={subject === "forecast" && horizon === "5d" ? "63d" : horizon} onChange={(event) => setHorizon(event.target.value)} className="ml-2 rounded border bg-background px-2 py-1"><option value="1d">1d</option><option value="5d">5d</option><option value="20d">20d</option><option value="63d">63d</option></select></label>
      </div>
      {!loading && data && <DataCoverageSummary freshness={data.freshness} coverage={data.coverage} />}
      {loading && <div className="h-32 animate-pulse rounded-xl bg-muted" />}
      {!loading && (!data || data.status === "no_data") && <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">暂无质量观测</div>}
      {!loading && data?.status === "insufficient_sample" && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-6 text-center"><p className="font-medium text-amber-600">样本不足</p><p className="mt-1 text-xs text-muted-foreground">至少需要 20 个可比样本，当前不会显示为 0。</p></div>}
      {!loading && data?.status === "available" && primary && (
        <>
          <div className="rounded-xl border bg-card p-5"><p className="text-xs text-muted-foreground">{primary.metric}</p><p className="mt-1 text-3xl font-semibold">{formatMetric(primary.metric, primary.value)}</p><div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground"><span>n={primary.sample_count}</span>{primary.interval_low != null && primary.interval_high != null && <span>95% 区间 {formatMetric(primary.metric, primary.interval_low)} – {formatMetric(primary.metric, primary.interval_high)}</span>}<span>{primary.formula_version}</span></div></div>
          <TrendChart title="质量趋势" points={trendPoints} metric={primary.metric} />
        </>
      )}
    </section>
  );
}
