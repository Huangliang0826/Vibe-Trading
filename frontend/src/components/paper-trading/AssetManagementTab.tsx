import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import {
  api,
  type AssetManagementCandidate,
  type ManualAllocation,
  type ManagedAssetType,
  type WatchlistMarket,
  type WatchlistQuote,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { PortfolioTools } from "./PortfolioTools";

const MANUAL_PORTFOLIO_KEY = "asset-management-manual-portfolio-v1";
const MARKETS: Array<{ market: WatchlistMarket; label: string }> = [
  { market: "hk", label: "港股自选" },
  { market: "cn", label: "A股自选" },
  { market: "us", label: "美股自选" },
];

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

interface SavedManualPortfolio {
  selected: AssetManagementCandidate[];
  weights: Record<string, number>;
  cashWeight: number;
}

function loadManualPortfolio(): SavedManualPortfolio {
  try {
    const saved = JSON.parse(localStorage.getItem(MANUAL_PORTFOLIO_KEY) || "null") as SavedManualPortfolio | null;
    if (saved && Array.isArray(saved.selected) && saved.weights && typeof saved.cashWeight === "number") return saved;
  } catch {
    // Ignore malformed local state and start with an empty manual portfolio.
  }
  return { selected: [], weights: {}, cashWeight: 0 };
}

export function AssetManagementTab() {
  const [initialPortfolio] = useState(loadManualPortfolio);
  const [quotes, setQuotes] = useState<Record<WatchlistMarket, WatchlistQuote[]>>({ hk: [], cn: [], us: [] });
  const [selected, setSelected] = useState<AssetManagementCandidate[]>(initialPortfolio.selected);
  const [manualMarket, setManualMarket] = useState<WatchlistMarket>("hk");
  const [manualType, setManualType] = useState<ManagedAssetType>("stock");
  const [manualSymbol, setManualSymbol] = useState("");
  const [loadingQuotes, setLoadingQuotes] = useState(true);
  const [weights, setWeights] = useState<Record<string, number>>(initialPortfolio.weights);
  const [cashWeight, setCashWeight] = useState(initialPortfolio.cashWeight);

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
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    localStorage.setItem(MANUAL_PORTFOLIO_KEY, JSON.stringify({ selected, weights, cashWeight }));
  }, [cashWeight, selected, weights]);

  const selectedKeys = useMemo(() => new Set(selected.map(keyOf)), [selected]);
  const totalWeight = selected.reduce((sum, item) => sum + (weights[keyOf(item)] || 0), cashWeight);
  const finalAllocations: ManualAllocation[] = [
    ...selected.map((item) => ({ ...item, weight: (weights[keyOf(item)] || 0) / 100 })),
    { symbol: "CASH", market: "cash", name: "现金", asset_type: "cash", weight: cashWeight / 100 },
  ];
  const validAllocation = selected.length > 0
    && finalAllocations.every((item) => item.weight >= 0 && item.weight <= 1)
    && Math.abs(totalWeight - 100) < 0.001;

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

  return (
    <div className="space-y-5">
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">候选资产</h2>
            <p className="text-xs text-muted-foreground">从自选或代码输入中加入标的，所有资产类型和比例均由你手动设置。</p>
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
        <div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold">手动配置资产比例</h2><p className="text-xs text-muted-foreground">每项比例会自动保存；回测和追踪不会调用组合优化器。</p></div><button type="button" disabled={!selected.length} onClick={() => { const equal = 100 / (selected.length + 1); setWeights(Object.fromEntries(selected.map((item) => [keyOf(item), equal]))); setCashWeight(equal); }} className="rounded border px-2 py-1 text-xs disabled:opacity-50">平均分配</button></div>
        {selected.length === 0 ? (
          <p className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">请先从自选或代码输入中加入候选资产</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[560px] text-sm">
              <thead><tr className="border-b text-muted-foreground"><th className="px-3 py-2 text-left font-medium">代码</th><th className="px-3 py-2 text-left font-medium">名称</th><th className="px-3 py-2 text-left font-medium">市场</th><th className="px-3 py-2 text-left font-medium">类型</th><th className="px-3 py-2 text-right font-medium">目标比例</th><th className="w-10"></th></tr></thead>
              <tbody>{selected.map((candidate, index) => (
                <tr key={keyOf(candidate)} className="border-b last:border-0">
                  <td className="px-3 py-2 font-mono">{candidate.symbol}</td><td className="px-3 py-2">{candidate.name}</td><td className="px-3 py-2">{candidate.market.toUpperCase()}</td>
                  <td className="px-3 py-2"><select value={candidate.asset_type} onChange={(event) => updateType(index, event.target.value as ManagedAssetType)} className="rounded border bg-background px-2 py-1 text-xs"><option value="stock">个股</option><option value="fund">基金/ETF</option><option value="bond">债券基金</option></select></td>
                  <td className="px-3 py-2 text-right"><div className="inline-flex items-center gap-1"><input aria-label={`${candidate.symbol} 目标比例`} type="number" min="0" max="100" step="0.1" value={weights[keyOf(candidate)] ?? 0} onChange={(event) => setWeights((current) => ({ ...current, [keyOf(candidate)]: Number(event.target.value) }))} className="w-20 rounded border bg-background px-2 py-1 text-right" /><span>%</span></div></td>
                  <td className="px-3 py-2"><button type="button" aria-label={`删除 ${candidate.symbol}`} onClick={() => setSelected((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="text-muted-foreground hover:text-red-500"><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              ))}<tr className="border-t bg-muted/20"><td className="px-3 py-2 font-mono">CASH</td><td className="px-3 py-2">现金</td><td className="px-3 py-2">USD</td><td className="px-3 py-2">现金</td><td className="px-3 py-2 text-right"><div className="inline-flex items-center gap-1"><input aria-label="现金目标比例" type="number" min="0" max="100" step="0.1" value={cashWeight} onChange={(event) => setCashWeight(Number(event.target.value))} className="w-20 rounded border bg-background px-2 py-1 text-right" /><span>%</span></div></td><td /></tr></tbody>
            </table>
          </div>
        )}
        <div className={cn("text-right text-sm font-medium", validAllocation ? "text-emerald-600" : "text-amber-600")}>合计 {totalWeight.toFixed(1)}%</div>

      </section>

      <PortfolioTools allocations={finalAllocations} valid={validAllocation} />
    </div>
  );
}
