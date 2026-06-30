import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ChevronDown, ChevronUp, Loader2, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  type OpportunityAction,
  type OpportunityDetail,
  type OpportunityFilters,
  type OpportunityHistoryPoint,
  type OpportunityItem,
  type OpportunityLevel,
  type OpportunityList,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { OpportunityHistoryChart } from "./OpportunityHistoryChart";
import { OpportunityCalibration } from "./OpportunityCalibration";

const DIMENSIONS = [
  ["strategy", "策略"], ["trend", "趋势"], ["risk", "风险"], ["news", "新闻"], ["valuation", "估值"],
] as const;
const ACTION_LABEL: Record<OpportunityAction, string> = {
  entry: "开仓", add: "加仓", hold: "持有", exit: "平仓", risk_exit: "降低仓位", wait: "等待", none: "无信号",
};

function rowKey(item: OpportunityItem) { return `${item.market}:${item.code}`; }
function forecastHref(item: OpportunityItem) { return `/forecast#forecast-card-${item.market}-${item.code.toUpperCase()}`; }

export function TodayOpportunities() {
  const [filters, setFilters] = useState<OpportunityFilters>({ market: "all", signal: "all", level: "all" });
  const [data, setData] = useState<OpportunityList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, OpportunityDetail>>({});
  const [histories, setHistories] = useState<Record<string, OpportunityHistoryPoint[]>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);
  const pollingJob = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api.getOpportunities(filters));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "机会数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setShowAll(false); }, [filters.market, filters.signal, filters.level]);
  useEffect(() => () => { if (pollTimer.current != null) window.clearTimeout(pollTimer.current); }, []);

  const pollJob = useCallback((jobId: string) => {
    if (pollingJob.current === jobId) return;
    pollingJob.current = jobId;
    const check = async () => {
      try {
        const job = await api.getOpportunityRefreshJob(jobId);
        if (job.status === "completed" || job.status === "failed") {
          pollingJob.current = null;
          pollTimer.current = null;
          await load();
          return;
        }
        pollTimer.current = window.setTimeout(check, 1000);
      } catch (reason) {
        pollingJob.current = null;
        pollTimer.current = null;
        setError(reason instanceof Error ? reason.message : "刷新状态获取失败");
      }
    };
    void check();
  }, [load]);

  useEffect(() => {
    const active = data?.active_job;
    if (active && (active.status === "queued" || active.status === "running") && pollTimer.current == null) {
      pollJob(active.job_id);
    }
  }, [data?.active_job, pollJob]);

  const refresh = async () => {
    try {
      setError(null);
      const job = await api.refreshOpportunities(["hk", "us"], false);
      setData((current) => current ? { ...current, active_job: job } : current);
      pollJob(job.job_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "刷新机会失败");
    }
  };

  const toggle = async (item: OpportunityItem) => {
    const key = rowKey(item);
    if (expanded === key) { setExpanded(null); return; }
    setExpanded(key);
    if (details[key]) return;
    setDetailLoading(key);
    try {
      const [detail, history] = await Promise.all([
        api.getOpportunityDetail(item.market, item.code),
        api.getOpportunityHistory(item.market, item.code, 30),
      ]);
      setDetails((current) => ({ ...current, [key]: detail }));
      setHistories((current) => ({ ...current, [key]: history }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "机会详情加载失败");
    } finally {
      setDetailLoading(null);
    }
  };

  const refreshing = data?.active_job?.status === "queued" || data?.active_job?.status === "running";
  const items = useMemo(() => data?.items ?? [], [data]);
  const visibleItems = showAll ? items : items.slice(0, 3);
  const hiddenCount = Math.max(0, items.length - 3);

  return (
    <section className="space-y-3" aria-labelledby="today-opportunities-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="today-opportunities-title" className="text-sm font-semibold text-foreground">今日机会</h2>
          <p className="text-[11px] text-muted-foreground">
            {data?.latest_success_at ? `数据截至 ${data.latest_success_at}` : "自选股策略、趋势、风险与新闻综合排序"}
          </p>
        </div>
        <button
          type="button" onClick={refresh} disabled={refreshing}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border text-muted-foreground transition hover:text-foreground disabled:opacity-50"
          aria-label="刷新机会" title="刷新机会"
        >
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </button>
      </div>

      {refreshing && data?.active_job && (
        <p className="text-[11px] text-muted-foreground">刷新进度 {data.active_job.completed}/{data.active_job.total}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border p-0.5" aria-label="市场筛选">
          {(["all", "hk", "us"] as const).map((market) => (
            <button key={market} type="button" onClick={() => setFilters((value) => ({ ...value, market }))}
              className={cn("h-7 rounded-md px-3 text-xs", filters.market === market ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}
            >{market === "all" ? "全部" : market === "hk" ? "港股" : "美股"}</button>
          ))}
        </div>
        <select aria-label="信号筛选" value={filters.signal} onChange={(event) => setFilters((value) => ({ ...value, signal: event.target.value as OpportunityFilters["signal"] }))}
          className="h-8 rounded-lg border bg-background px-2 text-xs text-foreground">
          <option value="all">全部信号</option><option value="entry">开仓</option><option value="add">加仓</option>
          <option value="hold">持有</option><option value="exit">平仓</option><option value="risk_exit">降低仓位</option><option value="wait">等待</option>
        </select>
        <select aria-label="机会等级筛选" value={filters.level} onChange={(event) => setFilters((value) => ({ ...value, level: event.target.value as OpportunityFilters["level"] }))}
          className="h-8 rounded-lg border bg-background px-2 text-xs text-foreground">
          <option value="all">全部等级</option><option value="优先关注">优先关注</option><option value="值得观察">值得观察</option>
          <option value="暂不参与">暂不参与</option><option value="数据不足">数据不足</option>
        </select>
      </div>

      {error && <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600"><AlertCircle className="h-4 w-4" />{error}</div>}
      {data?.last_refresh_error && !error && <p className="text-xs text-amber-600">上次刷新部分失败：{data.last_refresh_error}</p>}

      {loading ? (
        <div className="h-24 animate-pulse rounded-lg border bg-muted/30" />
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">暂无机会快照，点击刷新开始计算</div>
      ) : (
        <div className="space-y-2">
          {visibleItems.map((item) => {
            const key = rowKey(item);
            const open = expanded === key;
            const detail = details[key];
            return (
              <article key={key} className="rounded-lg border bg-card px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Link to={forecastHref(item)} className="block w-fit max-w-full hover:opacity-70" aria-label={`${item.company_name} ${item.code}`}>
                      <span className="text-sm font-semibold text-foreground">{item.company_name}</span>
                      <span className="ml-2 font-mono text-[11px] text-muted-foreground">{item.code}</span>
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                      <LevelBadge level={item.level} />
                      <ActionBadge action={item.latest_action} />
                      {item.strategy_label && <span className="text-muted-foreground">{item.strategy_label}</span>}
                      {item.signal_date && <span className="text-muted-foreground">{item.signal_date}</span>}
                      {(item.stale || item.degraded) && <span className="text-amber-600">{item.stale ? "数据已过期" : "部分数据降级"}</span>}
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">{item.primary_reason}</p>
                  </div>
                  <div className="flex shrink-0 items-start gap-2">
                    <div className="text-right">
                      <p className="text-xl font-semibold tabular-nums text-foreground">{item.score?.toFixed(1) ?? "—"}</p>
                      {item.score_change != null && <p className={cn("text-[11px] tabular-nums", item.score_change >= 0 ? "text-red-500" : "text-emerald-600")}>{item.score_change >= 0 ? "+" : ""}{item.score_change.toFixed(1)}</p>}
                    </div>
                    <button type="button" onClick={() => void toggle(item)} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted"
                      aria-label={`${open ? "收起" : "展开"}${item.company_name}机会详情`} title={open ? "收起详情" : "展开详情"}>
                      {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                {open && (
                  <div className="mt-3 border-t pt-3">
                    {detailLoading === key ? <div className="flex h-20 items-center justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div> : detail ? (
                      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
                        <div className="space-y-4">
                          <DimensionBars item={detail} />
                          {detail.risk_reasons.length > 0 && <div><h3 className="text-xs font-medium">风险提示</h3><ul className="mt-1 space-y-1 text-xs text-muted-foreground">{detail.risk_reasons.map((reason) => <li key={reason}>• {reason}</li>)}</ul></div>}
                          {detail.missing_dimensions.length > 0 && <p className="text-xs text-amber-600">缺失维度：{detail.missing_dimensions.join("、")}</p>}
                          <NewsList detail={detail} />
                        </div>
                        <div><h3 className="mb-1 text-xs font-medium">近 30 个快照</h3><OpportunityHistoryChart points={histories[key] ?? []} /></div>
                      </div>
                    ) : null}
                  </div>
                )}
              </article>
            );
          })}
          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
              aria-label={showAll ? "收起机会列表" : `查看其余 ${hiddenCount} 只`}
            >
              {showAll ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              {showAll ? "收起" : `查看其余 ${hiddenCount} 只`}
            </button>
          )}
        </div>
      )}
      <OpportunityCalibration />
      <p className="text-[11px] text-muted-foreground">机会评分仅用于研究排序，不构成投资建议。</p>
    </section>
  );
}

function LevelBadge({ level }: { level: OpportunityLevel }) {
  return <span className={cn("rounded-md px-1.5 py-0.5 font-medium", level === "优先关注" ? "bg-red-500/10 text-red-600" : level === "值得观察" ? "bg-amber-500/10 text-amber-600" : level === "数据不足" ? "bg-muted text-muted-foreground" : "bg-emerald-500/10 text-emerald-600")}>{level}</span>;
}

function ActionBadge({ action }: { action: OpportunityAction }) {
  return <span className={cn("font-medium", action === "entry" || action === "add" ? "text-red-500" : action === "exit" || action === "risk_exit" ? "text-emerald-600" : "text-muted-foreground")}>{ACTION_LABEL[action]}</span>;
}

function DimensionBars({ item }: { item: OpportunityDetail }) {
  return <div className="space-y-2">{DIMENSIONS.map(([key, label]) => { const value = item.dimensions[key]; return <div key={key} className="grid grid-cols-[32px_1fr_34px] items-center gap-2 text-[11px]"><span className="text-muted-foreground">{label}</span><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-foreground/60" style={{ width: `${value ?? 0}%` }} /></div><span className="text-right tabular-nums text-muted-foreground">{value?.toFixed(0) ?? "—"}</span></div>; })}</div>;
}

function NewsList({ detail }: { detail: OpportunityDetail }) {
  if (!detail.news.length) return <p className="text-xs text-muted-foreground">暂无相关已分析新闻</p>;
  return <div><h3 className="text-xs font-medium">相关新闻</h3><ul className="mt-1 space-y-2">{detail.news.slice(0, 5).map((news) => <li key={news.article_id} className="text-xs"><a href={news.url || undefined} target="_blank" rel="noreferrer" className={cn("text-foreground", news.url && "hover:underline")}>{news.title || news.summary || "新闻影响分析"}</a><p className="mt-0.5 text-[11px] text-muted-foreground">{news.source}{news.published_at ? ` · ${news.published_at.slice(0, 10)}` : ""} · {news.direction === "positive" ? "利好" : news.direction === "negative" ? "利空" : "中性"}</p></li>)}</ul></div>;
}
