import { FormEvent, useEffect, useState } from "react";

import { api, type StrategyComparisonRun } from "@/lib/api";

import { StrategyComparisonCharts } from "./StrategyComparisonCharts";

function isoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateYearsAgo(years: number): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() - years);
  return isoDate(date);
}

const pct = (value: number | null | undefined) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const num = (value: number | null | undefined) => value == null ? "—" : value.toFixed(2);

const metricItems = [
  ["年化收益", "cagr", pct],
  ["最大回撤", "max_drawdown", pct],
  ["Sharpe", "sharpe", num],
  ["Calmar", "calmar", num],
  ["年化波动", "annual_vol", pct],
  ["平均现金", "average_cash_ratio", pct],
] as const;

export function StrategyComparisonTab() {
  const [startDate, setStartDate] = useState(() => dateYearsAgo(5));
  const [endDate, setEndDate] = useState(() => isoDate(new Date()));
  const [initialCapital, setInitialCapital] = useState(100_000);
  const [costBps, setCostBps] = useState(20);
  const [run, setRun] = useState<StrategyComparisonRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        setRun(await api.getStrategyComparison(run.run_id));
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : "读取比较结果失败");
      }
    }, 1_000);
    return () => window.clearTimeout(timer);
  }, [run]);

  const selectRange = (years: number) => {
    setStartDate(dateYearsAgo(years));
    setEndDate(isoDate(new Date()));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setRun(null);
    try {
      setRun(await api.createStrategyComparison({
        start_date: startDate,
        end_date: endDate,
        initial_capital: initialCapital,
        cost_bps: costBps,
      }));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "创建比较任务失败");
    } finally {
      setSubmitting(false);
    }
  };

  const terminal = run && ["completed", "partial", "failed"].includes(run.status);

  return (
    <div className="space-y-5">
      <section className="rounded-xl border bg-card p-5">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">统一策略比较</h2>
          <p className="mt-1 text-sm text-muted-foreground">同一区间、同一初始资金与交易成本，比较三种资金配置方法。</p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {[1, 3, 5, 10].map((years) => (
              <button key={years} type="button" onClick={() => selectRange(years)} className="rounded-md border px-3 py-1.5 text-xs hover:bg-muted">
                近 {years} 年
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm">
              <span>开始日期</span>
              <input aria-label="开始日期" type="date" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} className="w-full rounded-md border bg-background px-3 py-2" required />
            </label>
            <label className="space-y-1 text-sm">
              <span>结束日期</span>
              <input aria-label="结束日期" type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} className="w-full rounded-md border bg-background px-3 py-2" required />
            </label>
            <label className="space-y-1 text-sm">
              <span>初始资金（USD）</span>
              <input type="number" min={1_000} step={1_000} value={initialCapital} onChange={(event) => setInitialCapital(Number(event.target.value))} className="w-full rounded-md border bg-background px-3 py-2" required />
            </label>
            <label className="space-y-1 text-sm">
              <span>交易成本（bps）</span>
              <input type="number" min={0} max={1_000} value={costBps} onChange={(event) => setCostBps(Number(event.target.value))} className="w-full rounded-md border bg-background px-3 py-2" required />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" disabled={submitting || run?.status === "queued" || run?.status === "running"} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {submitting ? "正在创建…" : run?.status === "queued" || run?.status === "running" ? "计算中…" : "运行统一比较"}
            </button>
            <span className="text-xs text-muted-foreground">信号在当日收盘计算，下一交易日开盘执行；现金收益率按 0% 计算。</span>
          </div>
        </form>
        {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      </section>

      {run && !terminal && (
        <section className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">正在加载市场数据并计算三条策略曲线…</section>
      )}

      {terminal && run && (
        <>
          {run.survivorship_bias && (
            <section className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
              <p className="font-medium text-amber-700 dark:text-amber-300">存在幸存者偏差：Strategy V0 使用当前标普成分股面板，不代表历史时点可投资股票池。</p>
              <p className="mt-1 text-xs text-muted-foreground">股票池来源日期：{run.universe_source_date}。结果仅供初筛，不能视为正式样本外验证。</p>
            </section>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            {run.results.map((result) => (
              <section key={result.key} className="rounded-xl border bg-card p-4">
                <div className="mb-3 flex items-start justify-between gap-2">
                  <h3 className="font-semibold">{result.label}</h3>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${result.status === "completed" ? "bg-emerald-500/10 text-emerald-600" : "bg-amber-500/10 text-amber-600"}`}>
                    {result.status === "completed" ? "已完成" : "不可用"}
                  </span>
                </div>
                {result.metrics ? (
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    {metricItems.map(([label, key, format]) => (
                      <div key={key}>
                        <dt className="text-xs text-muted-foreground">{label}</dt>
                        <dd className="mt-0.5 font-mono text-sm">{format(result.metrics?.[key])}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {result.key === "defensive_momentum_v0" ? "Strategy V0 暂不可用" : `${result.label} 暂不可用`}：{result.error ?? "数据不足"}
                  </p>
                )}
              </section>
            ))}
          </div>

          {run.results.some((result) => result.status === "completed" && result.points.length > 0) && <StrategyComparisonCharts results={run.results} />}

          <section className="rounded-xl border bg-card p-4">
            <h3 className="mb-3 text-sm font-semibold">验证记分卡</h3>
            <div className="grid gap-2 md:grid-cols-2">
              {run.scorecard.map((item) => (
                <div key={item.key} className="rounded-lg bg-muted/50 p-3 text-sm">
                  <div className="flex justify-between gap-3"><span className="font-medium">{item.label}</span><span className="uppercase text-xs text-muted-foreground">{item.status}</span></div>
                  <p className="mt-1 text-xs text-muted-foreground">{item.detail.includes("存在幸存者偏差") ? "见上方股票池偏差风险提示。" : item.detail}</p>
                </div>
              ))}
            </div>
          </section>

          {run.warnings.length > 0 && (
            <section className="rounded-xl border bg-card p-4 text-xs text-muted-foreground">
              <h3 className="mb-2 text-sm font-semibold text-foreground">口径说明</h3>
              <ul className="list-disc space-y-1 pl-5">{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
