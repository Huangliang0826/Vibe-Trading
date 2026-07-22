import { useEffect, useRef, useState } from "react";
import { BarChart3, PlayCircle, RefreshCw } from "lucide-react";
import { api, type AssetEquityPoint, type ManualAllocation, type PortfolioBacktestResult, type TrackingPortfolio } from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";

const money = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;

function CurveChart({ points, name }: { points: AssetEquityPoint[]; name: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useDarkMode();
  useEffect(() => {
    if (!ref.current || !points.length) return;
    const theme = getChartTheme();
    const chart = echarts.init(ref.current);
    chart.setOption({
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => money(Number(value)) },
      grid: { left: 62, right: 18, top: 24, bottom: 38 },
      xAxis: { type: "category", data: points.map((point) => point.date), boundaryGap: false },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (value: number) => `$${Math.round(value / 1000)}k` } },
      series: [{ name, type: "line", showSymbol: false, smooth: false, data: points.map((point) => point.value), lineStyle: { color: theme.infoColor }, areaStyle: { color: theme.infoColor, opacity: 0.08 } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [dark, name, points]);
  return <div ref={ref} className="h-64 w-full" />;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border px-3 py-2"><p className="text-[11px] text-muted-foreground">{label}</p><p className="font-semibold tabular-nums">{value}</p></div>;
}

export function PortfolioTools({ allocations, valid }: { allocations: ManualAllocation[]; valid: boolean }) {
  const [backtest, setBacktest] = useState<PortfolioBacktestResult | null>(null);
  const [tracking, setTracking] = useState<TrackingPortfolio | null>(null);
  const [busy, setBusy] = useState<"backtest" | "tracking" | "refresh" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => api.getLatestAssetTracking().then((value) => { if (!cancelled) setTracking(value); }).catch(() => {});
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const definition = { allocations, initial_capital: 100_000, installments: 10, interval_days: 7 };
  const runBacktest = async () => {
    setBusy("backtest"); setError(null);
    try { setBacktest(await api.backtestAssetPortfolio({ ...definition, years: 5, rebalance_months: 3 })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "回测失败"); }
    finally { setBusy(null); }
  };
  const startTracking = async () => {
    setBusy("tracking"); setError(null);
    try { setTracking(await api.startAssetTracking(definition)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "启动追踪失败"); }
    finally { setBusy(null); }
  };
  const refreshTracking = async () => {
    setBusy("refresh"); setError(null);
    try { setTracking(await api.getLatestAssetTracking()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "刷新失败"); }
    finally { setBusy(null); }
  };

  return <div className="space-y-5">
    <section className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-sm font-semibold">验证与追踪</h2><p className="text-xs text-muted-foreground">严格使用上方最终比例；10万美元分十周建仓，回测在建仓完成后每三个月再平衡。</p></div>
        <div className="flex gap-2">
          <button type="button" disabled={!valid || busy !== null} onClick={runBacktest} className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm disabled:opacity-50"><BarChart3 className="h-4 w-4" />{busy === "backtest" ? "回测中" : "一键回测"}</button>
          <button type="button" disabled={!valid || busy !== null} onClick={startTracking} className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><PlayCircle className="h-4 w-4" />{busy === "tracking" ? "启动中" : "开始追踪"}</button>
        </div>
      </div>
      {!valid && <p className="text-xs text-amber-600">资产与现金比例合计达到100%后才能回测或追踪。</p>}
      {error && <p className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-600">{error}</p>}
    </section>

    {backtest && <section className="space-y-4 rounded-xl border bg-card p-4">
      <div><h2 className="text-sm font-semibold">五年十周建仓与季度再平衡回测</h2><p className="text-xs text-muted-foreground">{backtest.start_date} 至 {backtest.end_date} · {backtest.installments} 期建仓 · {backtest.investment_completed_date} 完成 · 季度再平衡 {backtest.rebalances} 次</p></div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6"><Metric label="期末价值" value={money(backtest.final_value)} /><Metric label="累计盈利" value={money(backtest.total_profit)} /><Metric label="年化复合收益" value={pct(backtest.cagr)} /><Metric label="年度平均收益" value={pct(backtest.annual_average_return)} /><Metric label="最大回撤" value={pct(backtest.max_drawdown)} /><Metric label="年化波动" value={pct(backtest.annual_volatility)} /></div>
      <CurveChart points={backtest.curve} name="回测净值" />
      <div className="flex flex-wrap gap-2">{backtest.annual_returns.map((item) => <span key={item.year} className="rounded border px-2 py-1 text-xs">{item.year}：{pct(item.return_rate)}</span>)}</div>
      {backtest.rebalance_dates.length > 0 && <details className="rounded-lg border px-3 py-2 text-xs"><summary className="cursor-pointer font-medium">查看季度再平衡日期（{backtest.rebalances}次）</summary><div className="mt-2 flex flex-wrap gap-1.5">{backtest.rebalance_dates.map((value) => <span key={value} className="rounded bg-muted px-2 py-1">{value}</span>)}</div></details>}
      {backtest.warnings.length > 0 && <ul className="list-disc space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/5 px-7 py-2 text-xs text-muted-foreground">{backtest.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
    </section>}

    {tracking && <section className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-3"><div><h2 className="text-sm font-semibold">10万美元虚拟组合</h2><p className="text-xs text-muted-foreground">第 {tracking.completed_installments}/{tracking.total_installments} 期 · {tracking.next_installment_date ? `下期建仓 ${tracking.next_installment_date}` : `已完成建仓 · 季度再平衡 ${tracking.completed_rebalances} 次 · 下次 ${tracking.next_rebalance_date || "待定"}`} · 更新于 {tracking.last_updated}</p>{tracking.last_rebalance_date && <p className="mt-1 text-[11px] text-muted-foreground">最近一次再平衡：{tracking.last_rebalance_date}</p>}</div><button type="button" aria-label="刷新追踪" onClick={refreshTracking} disabled={busy !== null} className="rounded border p-2"><RefreshCw className={`h-4 w-4 ${busy === "refresh" ? "animate-spin" : ""}`} /></button></div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5"><Metric label="当前资产" value={money(tracking.current_value)} /><Metric label="累计收益" value={pct(tracking.cumulative_return)} /><Metric label="今日收益" value={pct(tracking.today_return)} /><Metric label="战略现金" value={money(tracking.strategic_cash)} /><Metric label="待建仓现金" value={money(tracking.deployment_cash)} /></div>
      {tracking.curve.length > 0 && <CurveChart points={tracking.curve} name="追踪净值" />}
      <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[680px] text-sm"><thead><tr className="border-b text-muted-foreground"><th className="px-3 py-2 text-left">资产</th><th className="px-3 py-2 text-right">数量</th><th className="px-3 py-2 text-right">当前价值</th><th className="px-3 py-2 text-right">目标仓位</th><th className="px-3 py-2 text-right">实际仓位</th><th className="px-3 py-2 text-right">价格日期</th></tr></thead><tbody>{tracking.positions.map((position) => <tr key={`${position.market}:${position.symbol}`} className="border-b last:border-0"><td className="px-3 py-2">{position.name} <span className="font-mono text-xs text-muted-foreground">{position.symbol}</span></td><td className="px-3 py-2 text-right tabular-nums">{position.quantity.toFixed(4)}</td><td className="px-3 py-2 text-right">{money(position.value_usd)}</td><td className="px-3 py-2 text-right">{pct(position.target_weight)}</td><td className="px-3 py-2 text-right">{pct(position.actual_weight)}</td><td className="px-3 py-2 text-right text-xs">{position.price_date}</td></tr>)}</tbody></table></div>
      {tracking.warnings.length > 0 && <ul className="list-disc space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/5 px-7 py-2 text-xs text-muted-foreground">{tracking.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
    </section>}
  </div>;
}
