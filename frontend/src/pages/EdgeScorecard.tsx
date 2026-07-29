import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Gauge, CheckCircle2, XCircle, CircleHelp, RefreshCw, Loader2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type EdgeScorecardResponse, type EdgeScorecardRow } from "@/lib/api";

const SOURCE_LABEL: Record<string, string> = {
  scanner: "机会扫描",
  forecast: "走势预测",
  paper_trading: "模拟盘",
};
const SOURCE_LINK: Record<string, string> = {
  scanner: "/scanner",
  forecast: "/forecast",
  paper_trading: "/paper-trading",
};
const MARKET_LABEL: Record<string, string> = { us: "美股", hk: "港股", cn: "A股", multi: "多市场" };

function horizonLabel(h: string): string {
  if (h === "run") return "回测";
  if (h === "pooled" || h === "unknown") return "";
  const m = /^(\d+)d$/.exec(h);
  return m ? `${m[1]}日` : h;
}

function fmtValue(row: EdgeScorecardRow): string {
  const v = row.value;
  if (v === null || v === undefined) return "—";
  if (row.unit === "accuracy") return `${(v * 100).toFixed(1)}%`;
  if (row.unit === "sharpe") return v.toFixed(2);
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`; // pct
}
function fmtBaseline(row: EdgeScorecardRow): string {
  if (row.unit === "accuracy") return `${(row.baseline * 100).toFixed(0)}%`;
  if (row.unit === "sharpe") return row.baseline.toFixed(1);
  return `${row.baseline.toFixed(0)}%`;
}
function fmtInterval(row: EdgeScorecardRow): string | null {
  if (row.interval_low === null || row.interval_high === null) return null;
  const f = (x: number) => (row.unit === "accuracy" ? `${(x * 100).toFixed(1)}%` : row.unit === "sharpe" ? x.toFixed(2) : `${x.toFixed(2)}%`);
  return `${f(row.interval_low)} ~ ${f(row.interval_high)}`;
}

type Badge = { label: string; className: string; icon: typeof CheckCircle2; strong: boolean };

// Confidence-aware: only interval-backed positives earn the green "有优势";
// point estimates (e.g. scanner spread, backtest Sharpe) are "初步为正" —
// realized-positive but not statistically demonstrated.
function verdictBadge(row: EdgeScorecardRow): Badge {
  if (row.verdict === "insufficient") return { label: "数据不足", className: "bg-muted text-muted-foreground", icon: CircleHelp, strong: false };
  if (row.verdict === "edge") {
    return row.confidence === "significant"
      ? { label: "有优势", className: "bg-success/12 text-success", icon: CheckCircle2, strong: true }
      : { label: "初步为正", className: "bg-info/12 text-info", icon: CheckCircle2, strong: false };
  }
  return { label: "未证实", className: "bg-warning/12 text-warning", icon: XCircle, strong: false };
}

function ScoreRow({ row }: { row: EdgeScorecardRow }) {
  const meta = verdictBadge(row);
  const Icon = meta.icon;
  const interval = fmtInterval(row);
  const provider = ["all", "pooled", "unknown", ""].includes(row.subject_id) ? "" : row.subject_id;
  const title = [MARKET_LABEL[row.market] ?? row.market, horizonLabel(row.horizon), provider].filter(Boolean).join(" · ");
  return (
    <div className="soft-card flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Link to={SOURCE_LINK[row.source] ?? "#"} className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent hover:underline">
            {SOURCE_LABEL[row.source] ?? row.source}
          </Link>
          {row.freshness === "stale" && (
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">数据偏旧</span>
          )}
        </div>
        <p className="mt-0.5 text-[15px] font-medium">{title || row.subject_id}</p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{row.metric_label}</p>
      </div>

      <div className="flex shrink-0 items-center gap-5">
        <div className="text-right">
          <p className={cn("text-xl font-semibold tabular-nums", meta.strong ? "text-success" : "text-foreground")}>
            {fmtValue(row)}
          </p>
          <p className="text-[10px] text-muted-foreground">
            基准 {fmtBaseline(row)}
            {row.cost_applied > 0 && ` · 扣成本 −${row.cost_applied.toFixed(2)}%`}
          </p>
          {interval && <p className="text-[10px] text-muted-foreground/80">95% 区间 {interval}</p>}
        </div>
        <div className="w-[92px] text-right">
          <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium", meta.className)}>
            <Icon className="h-3.5 w-3.5" />
            {meta.label}
          </span>
          <p className="mt-1 text-[10px] text-muted-foreground">
            {row.verdict === "insufficient" ? `样本 ${row.sample_count}` : `n=${row.sample_count}`}
            {row.confidence === "point_estimate" && row.verdict !== "insufficient" && " · 点估计"}
          </p>
        </div>
      </div>
    </div>
  );
}

export function EdgeScorecard({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<EdgeScorecardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [costBps, setCostBps] = useState(15);

  const load = useCallback((cost: number) => {
    setLoading(true);
    setError(null);
    api.getEdgeScorecard(90, cost)
      .then(setData)
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(costBps); }, [load, costBps]);

  const grouped = useMemo(() => {
    const order = ["scanner", "forecast", "paper_trading"];
    const by: Record<string, EdgeScorecardRow[]> = {};
    for (const r of data?.rows ?? []) (by[r.source] ??= []).push(r);
    return order.filter((s) => by[s]?.length).map((s) => ({ source: s, rows: by[s] }));
  }, [data]);

  const counts = useMemo(() => {
    const rows = data?.rows ?? [];
    return {
      strong: rows.filter((r) => r.verdict === "edge" && r.confidence === "significant").length,
      prelim: rows.filter((r) => r.verdict === "edge" && r.confidence !== "significant").length,
      noEdge: rows.filter((r) => r.verdict === "no_edge").length,
      insufficient: rows.filter((r) => r.verdict === "insufficient").length,
    };
  }, [data]);

  return (
    <div className={cn("mx-auto max-w-4xl space-y-6 px-4 sm:px-6", embedded ? "pb-7 pt-4 sm:pb-9" : "py-7 sm:py-9")}>
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/10">
          <Gauge className="h-5 w-5" strokeWidth={1.8} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="page-kicker">Edge scorecard</p>
          <h1 className="mt-1.5 text-[30px] font-semibold leading-tight tracking-[-0.035em] sm:text-[32px]">信号体检</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            扣成本、对基准、样本外——诚实回答每一路信号到底有没有优势。
          </p>
        </div>
        <button
          onClick={() => load(costBps)}
          disabled={loading}
          className="hidden shrink-0 items-center gap-1.5 rounded-xl border bg-card/75 px-3 py-2 text-xs font-medium text-muted-foreground transition hover:border-primary/25 hover:text-primary disabled:opacity-50 sm:inline-flex"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          刷新
        </button>
      </div>

      {/* Controls + summary */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-xs">
          <span className="text-muted-foreground">成本假设</span>
          {[5, 15, 30].map((b) => (
            <button
              key={b}
              onClick={() => setCostBps(b)}
              className={cn("rounded-md px-2 py-0.5 font-medium transition", costBps === b ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              {b}bps
            </button>
          ))}
        </div>
        {data && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 className="h-3.5 w-3.5" />{counts.strong} 显著有优势</span>
            <span className="inline-flex items-center gap-1 text-info"><CheckCircle2 className="h-3.5 w-3.5" />{counts.prelim} 初步为正</span>
            <span className="inline-flex items-center gap-1 text-warning"><XCircle className="h-3.5 w-3.5" />{counts.noEdge} 未证实</span>
            <span className="inline-flex items-center gap-1 text-muted-foreground"><CircleHelp className="h-3.5 w-3.5" />{counts.insufficient} 数据不足</span>
          </div>
        )}
      </div>

      {/* Body */}
      {loading && !data ? (
        <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> 正在体检…
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-red-500/25 bg-red-500/5 px-6 py-10 text-center text-sm text-red-600 dark:text-red-400">{error}</div>
      ) : grouped.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed bg-card/60 px-6 py-16 text-center">
          <Gauge className="h-8 w-8 text-muted-foreground/40" />
          <p className="text-sm font-medium">还没有足够的信号数据</p>
          <p className="max-w-md text-xs leading-5 text-muted-foreground">
            体检基于已积累的研究质量记录。先去
            <Link to="/scanner" className="text-primary hover:underline"> 机会扫描 </Link>
            与
            <Link to="/forecast" className="text-primary hover:underline"> 走势预测 </Link>
            运行几次并等前瞻收益回填后,这里就会给出每路信号的诚实评分。
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.map(({ source, rows }) => (
            <div key={source}>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold">{SOURCE_LABEL[source] ?? source}</h2>
                <Link to={SOURCE_LINK[source] ?? "#"} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary">
                  打开 <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
              <div className="space-y-2">
                {rows.map((r) => <ScoreRow key={r.id} row={r} />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Honest methodology footnote */}
      <div className="rounded-2xl border border-border/70 bg-muted/20 p-4 text-[11px] leading-5 text-muted-foreground">
        <p className="font-medium text-foreground/80">怎么判定的</p>
        <p className="mt-1">
          「有优势」要求扣成本后的 95% 置信区间整体越过基准——区间跨越基准就诚实地记为「未证实优势」,而不是假装有效。
          机会扫描用<span className="text-foreground/70">多空价差</span>(天然对冲市场,即已相对基准)并按每腿 {costBps}bps 扣成本;
          走势预测用<span className="text-foreground/70">方向准确率</span>对比 50% 掷硬币基准(不涉及成本);
          模拟盘用已扣成本的<span className="text-foreground/70">夏普</span>,是单次回测的点估计,证据较弱。样本少于 20 一律判「数据不足」。
        </p>
      </div>
    </div>
  );
}
