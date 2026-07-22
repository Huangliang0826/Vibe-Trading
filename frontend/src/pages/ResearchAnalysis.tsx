import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, ChevronDown, ChevronRight, FileSearch, Loader2, RefreshCw, Search, Trash2 } from "lucide-react";
import { api, type ResearchAnalysisListParams, type ResearchAnalysisRun } from "@/lib/api";
import { cn } from "@/lib/utils";
import { analyticsSessionId, trackProductEvent } from "@/lib/analytics";

const RATING_LABEL: Record<string, string> = {
  buy: "买入倾向",
  hold: "持有/观望",
  sell: "卖出/减仓",
};

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
};

function badgeClass(statusOrRating?: string | null) {
  switch (statusOrRating) {
    case "buy":
    case "completed":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "sell":
    case "failed":
      return "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300";
    case "running":
    case "queued":
      return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function DetailSection({ title, children }: { title: string; children?: ReactNode }) {
  if (!children) return null;
  return (
    <section className="space-y-2 border-t pt-4">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <div className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{children}</div>
    </section>
  );
}

function todayString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function ResearchAnalysis() {
  const [symbol, setSymbol] = useState("0700.HK");
  const [analysisDate, setAnalysisDate] = useState(() => todayString());
  const [analysisMode, setAnalysisMode] = useState<"fast" | "full">("fast");
  const [query, setQuery] = useState("");
  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterRating, setFilterRating] = useState<"all" | "buy" | "hold" | "sell">("all");
  const [filterDate, setFilterDate] = useState("");
  const [runs, setRuns] = useState<ResearchAnalysisRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<ResearchAnalysisRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const pendingAnalytics = useRef(new Map<string, { started: number; sessionId: string }>());

  const activeRunId = selectedRun?.run_id;
  const activeIsLive = selectedRun?.status === "queued" || selectedRun?.status === "running";

  const filters = useMemo<ResearchAnalysisListParams>(() => ({
    symbol: filterSymbol.trim() || undefined,
    rating: filterRating,
    query: query.trim() || undefined,
    date: filterDate || undefined,
    limit: 100,
  }), [filterDate, filterRating, filterSymbol, query]);

  const loadRuns = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listResearchAnalysisRuns(filters);
      setRuns(res.items);
      setSelectedRun((current) => {
        if (current) {
          return res.items.find((item) => item.run_id === current.run_id) || current;
        }
        return res.items[0] || null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  useEffect(() => {
    if (!activeRunId || !activeIsLive) return;
    const timer = window.setInterval(async () => {
      try {
        const run = await api.getResearchAnalysisRun(activeRunId);
        setSelectedRun(run);
        setRuns((prev) => prev.map((item) => (item.run_id === run.run_id ? run : item)));
        if (run.status === "completed" || run.status === "failed") {
          const pending = pendingAnalytics.current.get(run.run_id);
          if (pending) {
            pendingAnalytics.current.delete(run.run_id);
            trackProductEvent({
              feature: "research_analysis",
              action: "task_complete",
              outcome: run.status === "completed" ? "success" : "failure",
              sessionId: pending.sessionId,
              durationMs: performance.now() - pending.started,
              metadata: { route: "/research-analysis", source: "multi_agent", mode: run.mode },
            });
            if (run.status === "completed") {
              trackProductEvent({ feature: "research_analysis", action: "result_view", outcome: "success", sessionId: pending.sessionId, metadata: { route: "/research-analysis", source: "multi_agent", mode: run.mode } });
            }
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [activeRunId, activeIsLive]);

  const createRun = async (nextSymbol = symbol, nextDate = analysisDate, nextMode = analysisMode) => {
    const trimmed = nextSymbol.trim();
    if (!trimmed) {
      setError("请输入股票代码，例如 AAPL、NVDA、0700.HK、9988.HK");
      return;
    }
    setCreating(true);
    setError(null);
    const started = performance.now();
    const sessionId = analyticsSessionId("/research-analysis");
    trackProductEvent({ feature: "research_analysis", action: "task_start", outcome: "unknown", sessionId, metadata: { route: "/research-analysis", source: "multi_agent" } });
    try {
      const run = await api.createResearchAnalysisRun({
        symbol: trimmed,
        market: "auto",
        analysis_date: nextDate || todayString(),
        mode: nextMode,
      });
      setSelectedRun(run);
      setRuns((prev) => [run, ...prev.filter((item) => item.run_id !== run.run_id)]);
      pendingAnalytics.current.set(run.run_id, { started, sessionId });
    } catch (err) {
      trackProductEvent({ feature: "research_analysis", action: "task_complete", outcome: "failure", sessionId, durationMs: performance.now() - started, metadata: { route: "/research-analysis", source: "multi_agent" } });
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const deleteRun = async (run: ResearchAnalysisRun) => {
    if (!window.confirm(`删除 ${run.symbol} 的这条投研分析记录？`)) return;
    try {
      await api.deleteResearchAnalysisRun(run.run_id);
      setRuns((prev) => prev.filter((item) => item.run_id !== run.run_id));
      setSelectedRun((current) => (current?.run_id === run.run_id ? null : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const rerun = (run: ResearchAnalysisRun) => {
    createRun(run.symbol, run.analysis_date || todayString(), run.mode || "fast");
  };

  const report = selectedRun?.report;
  const rawAnalysis = selectedRun?.report_markdown || (selectedRun?.raw_decision
    ? typeof selectedRun.raw_decision === "string"
      ? selectedRun.raw_decision
      : JSON.stringify(selectedRun.raw_decision, null, 2)
    : "");

  return (
    <div className="min-h-full">
      <div className="app-page app-page-wide flex flex-col">
        <div className="app-page-header">
          <div className="app-page-heading">
            <div className="app-page-icon"><FileSearch className="h-5 w-5" strokeWidth={1.8} /></div>
            <div>
              <p className="page-kicker">Research desk</p>
              <h1 className="app-page-title">投研分析</h1>
              <p className="app-page-description">TradingAgents 多智能体投研观点，本地永久归档；仅供研究参考，不构成投资建议。</p>
            </div>
          </div>
          <button
            onClick={loadRuns}
            className="app-button-secondary self-end sm:self-auto"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            刷新历史
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <section className="app-panel-compact">
              <h2 className="app-panel-title">新建分析</h2>
              <div className="mt-4 space-y-3">
                <label className="block text-xs font-medium text-muted-foreground">
                  股票代码
                  <input
                    value={symbol}
                    onChange={(event) => setSymbol(event.target.value)}
                    placeholder="AAPL / NVDA / 0700.HK"
                    className="app-field mt-1 w-full"
                  />
                </label>
                <label className="block text-xs font-medium text-muted-foreground">
                  分析日期
                  <input
                    type="date"
                    value={analysisDate}
                    onChange={(event) => setAnalysisDate(event.target.value)}
                    className="app-field mt-1 w-full"
                  />
                </label>
                <label className="block text-xs font-medium text-muted-foreground">
                  分析模式
                  <select
                    value={analysisMode}
                    onChange={(event) => setAnalysisMode(event.target.value as "fast" | "full")}
                    className="app-field mt-1 w-full"
                  >
                    <option value="fast">快速分析（推荐）</option>
                    <option value="full">完整分析</option>
                  </select>
                  <span className="mt-1 block font-normal leading-5">快速模式保留技术面、基本面和多空判断，跳过低价值社交数据与重复风控辩论。</span>
                </label>
                <button
                  disabled={creating}
                  onClick={() => createRun()}
                  className="app-button-primary w-full disabled:opacity-60"
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
                  开始投研分析
                </button>
              </div>
            </section>

            <section className="app-panel-compact overflow-hidden p-0">
              <div className="border-b px-4 py-3 text-sm font-semibold">本地归档</div>
              <div className="max-h-[520px] overflow-auto p-2">
                {loading && runs.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    加载中
                  </div>
                ) : runs.length === 0 ? (
                  <p className="px-3 py-8 text-center text-sm text-muted-foreground">暂无投研分析记录</p>
                ) : runs.map((run) => (
                  <button
                    key={run.run_id}
                    onClick={() => setSelectedRun(run)}
                    className={cn(
                      "mb-2 w-full rounded-2xl border bg-card p-3 text-left transition-colors hover:border-primary/25 hover:bg-muted/40",
                      selectedRun?.run_id === run.run_id && "border-primary bg-primary/5",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">
                          {run.symbol}{run.company_name ? ` · ${run.company_name}` : ""}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">{run.analysis_date}</div>
                      </div>
                      <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[11px]", badgeClass(run.status))}>
                        {STATUS_LABEL[run.status] || run.status}
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{run.summary || run.error || "等待结果"}</p>
                  </button>
                ))}
              </div>
            </section>

            <section className="app-panel-compact overflow-hidden p-0">
              <button
                onClick={() => setFiltersExpanded((value) => !value)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold hover:bg-muted"
              >
                <span>历史筛选</span>
                {filtersExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
              {filtersExpanded && (
                <div className="space-y-3 border-t p-4">
                  <label className="block text-xs font-medium text-muted-foreground">
                    全文搜索
                    <div className="relative mt-1">
                      <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                      <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="关键词"
                        className="app-field w-full py-2 pl-9 pr-3"
                      />
                    </div>
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      value={filterSymbol}
                      onChange={(event) => setFilterSymbol(event.target.value)}
                      placeholder="股票"
                      className="app-field w-full"
                    />
                    <select
                      value={filterRating}
                      onChange={(event) => setFilterRating(event.target.value as "all" | "buy" | "hold" | "sell")}
                      className="app-field w-full"
                    >
                      <option value="all">全部结论</option>
                      <option value="buy">买入倾向</option>
                      <option value="hold">持有/观望</option>
                      <option value="sell">卖出/减仓</option>
                    </select>
                  </div>
                  <input
                    type="date"
                    value={filterDate}
                    onChange={(event) => setFilterDate(event.target.value)}
                    className="app-field w-full"
                  />
                </div>
              )}
            </section>
          </aside>

          <main className="app-panel overflow-hidden p-0">
            {!selectedRun ? (
              <div className="flex min-h-[520px] items-center justify-center p-6 text-sm text-muted-foreground">
                选择一条历史记录，或新建一次投研分析。
              </div>
            ) : (
              <div className="space-y-5 p-5 sm:p-6">
                <div className="flex flex-col gap-3 border-b pb-4 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-xl font-semibold">
                        {selectedRun.symbol}{selectedRun.company_name ? ` · ${selectedRun.company_name}` : ""}
                      </h2>
                      <span className={cn("rounded-full border px-2 py-0.5 text-xs", badgeClass(selectedRun.status))}>
                        {STATUS_LABEL[selectedRun.status] || selectedRun.status}
                      </span>
                      {selectedRun.rating && (
                        <span className={cn("rounded-full border px-2 py-0.5 text-xs", badgeClass(selectedRun.rating))}>
                          {RATING_LABEL[selectedRun.rating] || selectedRun.rating}
                        </span>
                      )}
                      {typeof selectedRun.confidence === "number" && (
                        <span className="rounded-full border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          置信度 {selectedRun.confidence}/100
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {selectedRun.market.toUpperCase()} · {selectedRun.analysis_date} · {selectedRun.mode === "full" ? "完整分析" : "快速分析"} · {selectedRun.run_id}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => rerun(selectedRun)}
                      className="app-button-secondary"
                    >
                      <RefreshCw className="h-4 w-4" />
                      重新分析
                    </button>
                    <button
                      onClick={() => deleteRun(selectedRun)}
                      className="app-button-secondary text-red-600 hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                      删除
                    </button>
                  </div>
                </div>

                {(selectedRun.status === "queued" || selectedRun.status === "running") && (
                  <div className="flex items-center gap-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {selectedRun.summary || "后台分析运行中"}
                  </div>
                )}

                {selectedRun.status === "failed" && (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300">
                    {selectedRun.error || "分析失败"}
                  </div>
                )}

                {report && !report.structured ? (
                  <article className="prose prose-sm dark:prose-invert max-w-none rounded-2xl bg-muted/60 p-5">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {rawAnalysis || report.summary}
                    </ReactMarkdown>
                  </article>
                ) : report ? (
                  <article className="space-y-4">
                    <DetailSection title="核心结论">{report.summary}</DetailSection>
                    <DetailSection title="牛方观点">{report.bull_case}</DetailSection>
                    <DetailSection title="熊方观点">{report.bear_case}</DetailSection>
                    <DetailSection title="技术面">{report.technical_view}</DetailSection>
                    <DetailSection title="基本面">{report.fundamental_view}</DetailSection>
                    <DetailSection title="新闻与情绪">{report.sentiment_news_view}</DetailSection>
                    <DetailSection title="主要风险">
                      <ul className="list-disc space-y-1 pl-5">
                        {report.risk_factors.map((risk, index) => <li key={`${risk}-${index}`}>{risk}</li>)}
                      </ul>
                    </DetailSection>
                    <DetailSection title="建议动作">{report.suggested_action}</DetailSection>
                    <DetailSection title="声明">{report.disclaimer}</DetailSection>
                  </article>
                ) : selectedRun.report_markdown ? (
                  <article className="prose prose-sm dark:prose-invert max-w-none rounded-2xl bg-muted/60 p-5">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedRun.report_markdown}
                    </ReactMarkdown>
                  </article>
                ) : null}
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
