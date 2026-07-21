import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import {
  api,
  type AssetManagementCandidate,
  type AssetManagementPlan,
  type ManagedAssetType,
  type WatchlistMarket,
  type WatchlistQuote,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const RETURN_OPTIONS = [
  { value: 0.045, label: "4%–5% · 稳健" },
  { value: 0.065, label: "6%–7% · 平衡" },
  { value: 0.075, label: "7%–8% · 增长" },
  { value: 0.095, label: "9%–10% · 进取" },
];

const DRAWDOWN_OPTIONS = [0.10, 0.15, 0.20, 0.25, 0.30];
const MARKETS: Array<{ market: WatchlistMarket; label: string }> = [
  { market: "hk", label: "港股自选" },
  { market: "cn", label: "A股自选" },
  { market: "us", label: "美股自选" },
];

const TYPE_LABELS: Record<ManagedAssetType | "cash", string> = {
  stock: "个股",
  fund: "基金/ETF",
  bond: "债券基金",
  cash: "现金",
};

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatCalculatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function hasMeaningfulPlanChange(previous: AssetManagementPlan, next: AssetManagementPlan): boolean {
  if (previous.status !== next.status || previous.allocations.length !== next.allocations.length) return true;
  const previousWeights = new Map(previous.allocations.map((item) => [keyOf(item), item.weight]));
  return next.allocations.some((item) => {
    const previousWeight = previousWeights.get(keyOf(item));
    return previousWeight === undefined || Math.abs(previousWeight - item.weight) >= 0.0005;
  });
}

function keyOf(candidate: { market: string; symbol: string }): string {
  return `${candidate.market}:${candidate.symbol.toUpperCase()}`;
}

function loadLocalCodes(market: WatchlistMarket): string[] {
  try {
    return JSON.parse(localStorage.getItem(`watchlist-${market}`) || "[]");
  } catch {
    return [];
  }
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border bg-card px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-lg font-bold tabular-nums">{value}</p>
      <p className="text-[10px] text-muted-foreground/70">{hint}</p>
    </div>
  );
}

export function AssetManagementTab() {
  const [quotes, setQuotes] = useState<Record<WatchlistMarket, WatchlistQuote[]>>({ hk: [], cn: [], us: [] });
  const [selected, setSelected] = useState<AssetManagementCandidate[]>([]);
  const [targetReturn, setTargetReturn] = useState(0.075);
  const [maxDrawdown, setMaxDrawdown] = useState(0.20);
  const [manualMarket, setManualMarket] = useState<WatchlistMarket>("hk");
  const [manualType, setManualType] = useState<ManagedAssetType>("stock");
  const [manualSymbol, setManualSymbol] = useState("");
  const [plan, setPlan] = useState<AssetManagementPlan | null>(null);
  const [loadingQuotes, setLoadingQuotes] = useState(true);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [calculationNotice, setCalculationNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoadingQuotes(true);
      await Promise.all(MARKETS.map(async ({ market }) => {
        const response = await api.getWatchlistCodes(market).catch(() => ({ codes: loadLocalCodes(market) }));
        const codes = response.codes.length ? response.codes : loadLocalCodes(market);
        const marketQuotes = codes.length
          ? await api.getWatchlistQuote(codes, market).catch(() => [] as WatchlistQuote[])
          : [];
        if (!cancelled) setQuotes((current) => ({ ...current, [market]: marketQuotes }));
      }));
      if (!cancelled) setLoadingQuotes(false);
    };
    void load();
    api.getLatestAssetManagementPlan()
      .then((latest) => {
        if (cancelled || !latest) return;
        setPlan(latest);
        setSelected(latest.request.candidates);
        setTargetReturn(latest.request.target_return);
        setMaxDrawdown(latest.request.max_drawdown);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const selectedKeys = useMemo(() => new Set(selected.map(keyOf)), [selected]);

  const addCandidate = (candidate: AssetManagementCandidate) => {
    setSelected((current) => current.some((item) => keyOf(item) === keyOf(candidate)) ? current : [...current, candidate]);
  };

  const addQuote = (quote: WatchlistQuote, market: WatchlistMarket) => {
    addCandidate({ symbol: quote.code.toUpperCase(), market, name: quote.name || quote.code, asset_type: "stock" });
  };

  const addManual = () => {
    const symbol = manualSymbol.trim().toUpperCase();
    if (!symbol) return;
    addCandidate({ symbol, market: manualMarket, name: symbol, asset_type: manualType });
    setManualSymbol("");
  };

  const updateType = (index: number, assetType: ManagedAssetType) => {
    setSelected((current) => current.map((candidate, candidateIndex) => (
      candidateIndex === index ? { ...candidate, asset_type: assetType } : candidate
    )));
  };

  const calculate = async () => {
    if (!selected.length) return;
    setCalculating(true);
    setError(null);
    setCalculationNotice(null);
    try {
      const nextPlan = await api.calculateAssetManagementPlan({
        candidates: selected,
        target_return: targetReturn,
        max_drawdown: maxDrawdown,
        lookback_years: 5,
      });
      const changed = plan ? hasMeaningfulPlanChange(plan, nextPlan) : true;
      setPlan(nextPlan);
      setCalculationNotice(
        changed
          ? `计算完成 · ${formatCalculatedAt(nextPlan.created_at)}，配置结果已更新。`
          : `重新计算完成 · ${formatCalculatedAt(nextPlan.created_at)}。输入和行情数据未发生有效变化，因此建议比例保持不变。`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "资产配置计算失败");
    } finally {
      setCalculating(false);
    }
  };

  return (
    <div className="space-y-5">
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">候选资产</h2>
            <p className="text-xs text-muted-foreground">从自选中加入多个标的；加入候选池不代表一定获得仓位。</p>
          </div>
          {loadingQuotes && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          {MARKETS.map(({ market, label }) => (
            <div key={market} className="space-y-2">
              <p className="text-xs font-medium">{label}</p>
              {quotes[market].length === 0 ? (
                <p className="rounded-lg border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">暂无自选</p>
              ) : quotes[market].map((quote) => {
                const added = selectedKeys.has(`${market}:${quote.code.toUpperCase()}`);
                return (
                  <button
                    type="button"
                    key={`${market}:${quote.code}`}
                    onClick={() => addQuote(quote, market)}
                    disabled={added}
                    className="flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted/40 disabled:opacity-50"
                  >
                    <span className="min-w-0"><span className="block truncate font-medium">{quote.name || quote.code}</span><span className="font-mono text-muted-foreground">{quote.code}</span></span>
                    <span>{added ? "已加入" : "+ 加入"}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t pt-4">
          <label className="text-xs text-muted-foreground">市场
            <select value={manualMarket} onChange={(event) => setManualMarket(event.target.value as WatchlistMarket)} className="mt-1 block rounded-lg border bg-background px-2 py-1.5 text-sm text-foreground">
              <option value="hk">港股</option><option value="cn">A股</option><option value="us">美股</option>
            </select>
          </label>
          <label className="text-xs text-muted-foreground">类型
            <select value={manualType} onChange={(event) => setManualType(event.target.value as ManagedAssetType)} className="mt-1 block rounded-lg border bg-background px-2 py-1.5 text-sm text-foreground">
              <option value="stock">个股</option><option value="fund">基金/ETF</option><option value="bond">债券基金</option>
            </select>
          </label>
          <label className="min-w-48 flex-1 text-xs text-muted-foreground">代码
            <input value={manualSymbol} onChange={(event) => setManualSymbol(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addManual(); }} placeholder="输入股票或基金代码" className="mt-1 block w-full rounded-lg border bg-background px-3 py-1.5 text-sm text-foreground" />
          </label>
          <button type="button" onClick={addManual} className="flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"><Plus className="h-4 w-4" />添加</button>
        </div>
      </section>

      <section className="space-y-4 rounded-xl border bg-card p-4">
        <h2 className="text-sm font-semibold">已选资产与目标</h2>
        {selected.length === 0 ? (
          <p className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">请先从自选或代码输入中加入候选资产</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[560px] text-sm">
              <thead><tr className="border-b text-muted-foreground"><th className="px-3 py-2 text-left font-medium">代码</th><th className="px-3 py-2 text-left font-medium">名称</th><th className="px-3 py-2 text-left font-medium">市场</th><th className="px-3 py-2 text-left font-medium">类型</th><th className="w-10"></th></tr></thead>
              <tbody>{selected.map((candidate, index) => (
                <tr key={keyOf(candidate)} className="border-b last:border-0">
                  <td className="px-3 py-2 font-mono">{candidate.symbol}</td><td className="px-3 py-2">{candidate.name}</td><td className="px-3 py-2">{candidate.market.toUpperCase()}</td>
                  <td className="px-3 py-2"><select value={candidate.asset_type} onChange={(event) => updateType(index, event.target.value as ManagedAssetType)} className="rounded border bg-background px-2 py-1 text-xs"><option value="stock">个股</option><option value="fund">基金/ETF</option><option value="bond">债券基金</option></select></td>
                  <td className="px-3 py-2"><button type="button" aria-label={`删除 ${candidate.symbol}`} onClick={() => setSelected((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="text-muted-foreground hover:text-red-500"><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">预期年化收益
            <select value={targetReturn} onChange={(event) => setTargetReturn(Number(event.target.value))} className="mt-1 block w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground">
              {RETURN_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">最大可接受回撤
            <select value={maxDrawdown} onChange={(event) => setMaxDrawdown(Number(event.target.value))} className="mt-1 block w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground">
              {DRAWDOWN_OPTIONS.map((value) => <option key={value} value={value}>{pct(value)}</option>)}
            </select>
          </label>
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] text-muted-foreground">仓位由 DeepSeek 直接生成；本地只校验资产一致、非负且合计100%，并在生成后计算历史风险指标。</p>
          <button type="button" onClick={calculate} disabled={!selected.length || calculating} className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {calculating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{calculating ? "计算中" : plan ? "重新计算" : "生成配置"}
          </button>
        </div>
        {error && <p className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
        {calculationNotice && <p role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400">{calculationNotice}</p>}
      </section>

      {plan && (
        <section key={plan.plan_id} className="space-y-4 rounded-xl border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div><div className="flex items-center gap-2"><h2 className="text-sm font-semibold">最新资产配置</h2><span className={cn("rounded-full px-2 py-0.5 text-[11px]", plan.status === "feasible" ? "bg-emerald-500/10 text-emerald-600" : "bg-amber-500/10 text-amber-600")}>{plan.status === "feasible" ? "满足目标" : "最接近方案"}</span></div><p className="mt-1 text-xs text-muted-foreground">{plan.summary}</p></div>
            <div className="text-right text-[10px] text-muted-foreground"><p>计算于 {formatCalculatedAt(plan.created_at)}</p><p>数据截至 {plan.data_through} · {plan.provider}/{plan.model}</p></div>
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="预计年化收益" value={pct(plan.metrics.expected_return)} hint={`目标 ${pct(plan.metrics.target_return)}`} />
            <Stat label="年化波动" value={pct(plan.metrics.annual_volatility)} hint="基于历史协方差" />
            <Stat label="历史最大回撤" value={pct(plan.metrics.historical_max_drawdown)} hint="共同数据区间" />
            <Stat label="压力回撤" value={pct(plan.metrics.stress_drawdown)} hint={`上限 ${pct(-plan.metrics.max_drawdown_limit)}`} />
          </div>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-sm">
              <thead><tr className="border-b text-muted-foreground"><th className="px-3 py-2 text-left font-medium">资产</th><th className="px-3 py-2 text-left font-medium">类型</th><th className="px-3 py-2 text-right font-medium">建议比例</th><th className="px-3 py-2 text-right font-medium">允许区间</th><th className="px-3 py-2 text-right font-medium">风险贡献</th><th className="px-3 py-2 text-left font-medium">理由</th></tr></thead>
              <tbody>{plan.allocations.map((allocation) => (
                <tr key={`${allocation.market}:${allocation.symbol}`} className={cn("border-b last:border-0", allocation.weight === 0 && "text-muted-foreground")}>
                  <td className="px-3 py-2"><span className="font-medium">{allocation.name}</span><span className="ml-1 font-mono text-[11px] text-muted-foreground">{allocation.symbol}</span></td><td className="px-3 py-2">{TYPE_LABELS[allocation.asset_type]}</td><td className="px-3 py-2 text-right font-semibold tabular-nums">{pct(allocation.weight)}</td><td className="px-3 py-2 text-right tabular-nums">{pct(allocation.range_min)}–{pct(allocation.range_max)}</td><td className="px-3 py-2 text-right tabular-nums">{pct(allocation.risk_contribution)}</td><td className="px-3 py-2 text-xs text-muted-foreground">{allocation.reason}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {plan.warnings.length > 0 && <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2"><p className="text-xs font-medium">风险提示</p><ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
        </section>
      )}
    </div>
  );
}
