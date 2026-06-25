import { useEffect, useState, useRef, useCallback } from "react";
import { Briefcase, Plus, Trash2, Loader2, Play, ChevronDown, ChevronRight } from "lucide-react";
import { api, type PaperTradingRun, type PaperHolding, type PaperStrategyConfig, type PaperTrade, type WatchlistMarket, type WatchlistQuote } from "@/lib/api";
import { PaperEquityChart } from "@/components/charts/PaperEquityChart";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "bad" | "neutral" }) {
  const color = tone === "good" ? "text-emerald-600 dark:text-emerald-400"
    : tone === "bad" ? "text-red-500 dark:text-red-400"
    : "text-foreground";
  return (
    <div className="rounded-xl border bg-card px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={cn("text-lg font-bold tabular-nums leading-tight", color)}>{value}</p>
      {hint && <p className="text-[10px] text-muted-foreground/70 mt-0.5">{hint}</p>}
    </div>
  );
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(2)}%`;
}

function fmtMoney(v: number | null | undefined): string {
  return v == null ? "—" : `$${v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function fmtPrice(price: number, market: WatchlistMarket): string {
  if (!price) return "—";
  return market === "us"
    ? price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : price.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function fmtPctValue(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function changeColor(value: number) {
  if (value > 0) return "text-red-500 dark:text-red-400";
  if (value < 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-muted-foreground";
}

function loadWatchlistCodes(market: WatchlistMarket): string[] {
  try {
    return JSON.parse(localStorage.getItem(`watchlist-${market}`) || "[]");
  } catch {
    return [];
  }
}

function holdingKey(symbol: string, market: "us" | "hk"): string {
  return `${market}:${symbol.toUpperCase()}`;
}

type StrategyName =
  | "buy_and_hold"
  | "dca"
  | "grid"
  | "momentum_breakout"
  | "moving_average_cross"
  | "rsi_reversion"
  | "volatility_target"
  | "drawdown_rebalance"
  | "smart_dca";

const STRATEGY_OPTIONS: { value: StrategyName; label: string; desc: string }[] = [
  { value: "buy_and_hold", label: "Buy & Hold", desc: "买入并持有，不做任何调仓" },
  { value: "dca", label: "DCA 定投", desc: "按固定频率分批建仓" },
  { value: "grid", label: "网格交易", desc: "在价格区间内低买高卖" },
  { value: "momentum_breakout", label: "动量突破", desc: "突破近期高点买入，跌破趋势退出" },
  { value: "moving_average_cross", label: "均线交叉", desc: "短均线上穿长均线持有，下穿退出" },
  { value: "rsi_reversion", label: "RSI 低吸高抛", desc: "超卖买入，反弹到超买区卖出" },
  { value: "volatility_target", label: "波动率仓位", desc: "波动越高仓位越低，优先控制风险" },
  { value: "drawdown_rebalance", label: "回撤加仓", desc: "下跌分批提高仓位，接近前高降仓" },
  { value: "smart_dca", label: "智能定投增强", desc: "低估多投，过热少投，高波动降速" },
];

const STRATEGY_LABELS = Object.fromEntries(
  STRATEGY_OPTIONS.map((option) => [option.value, option.label]),
) as Record<StrategyName, string>;

function strategyParamsFor(name: StrategyName, dcaFrequency: string, gridCount: number): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (name === "dca" || name === "smart_dca") params.frequency = dcaFrequency;
  if (name === "grid") params.grid_count = gridCount;
  return params;
}

function compareRuns(a: PaperTradingRun, b: PaperTradingRun): number {
  const am = a.metrics ?? {};
  const bm = b.metrics ?? {};
  const sharpeDiff = finiteNumber(bm.sharpe, -Infinity) - finiteNumber(am.sharpe, -Infinity);
  if (Math.abs(sharpeDiff) > 1e-9) return sharpeDiff;
  const returnDiff = finiteNumber(bm.total_return, -Infinity) - finiteNumber(am.total_return, -Infinity);
  if (Math.abs(returnDiff) > 1e-9) return returnDiff;
  return finiteNumber(bm.max_drawdown, -Infinity) - finiteNumber(am.max_drawdown, -Infinity);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function WatchlistQuickAdd({
  title,
  market,
  quotes,
  holdings,
  onAdd,
}: {
  title: string;
  market: "hk" | "us";
  quotes: WatchlistQuote[];
  holdings: PaperHolding[];
  onAdd: (quote: WatchlistQuote, market: "hk" | "us") => void;
}) {
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      {quotes.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-card/50 px-3 py-5 text-center text-sm text-muted-foreground">
          暂无自选
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {quotes.map((quote) => {
            const added = holdings.some((h) => h.market === market && h.symbol.toUpperCase() === quote.code.toUpperCase());
            const color = changeColor(quote.change_pct);
            return (
              <div key={`${market}-${quote.code}`} className="flex items-center justify-between gap-3 rounded-xl border bg-card px-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{quote.name !== quote.code ? quote.name : quote.code}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">{quote.code}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <div className="text-right">
                    <p className={cn("text-sm font-bold tabular-nums", color)}>{fmtPrice(quote.price, market)}</p>
                    <p className={cn("text-[11px] tabular-nums", color)}>{fmtPctValue(quote.change_pct)}</p>
                  </div>
                  <button
                    onClick={() => onAdd(quote, market)}
                    disabled={added || quote.price <= 0}
                    className={cn(
                      "rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
                      added || quote.price <= 0
                        ? "cursor-not-allowed bg-muted text-muted-foreground"
                        : "bg-background hover:bg-accent",
                    )}
                  >
                    {added ? "已加入" : "加入"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function PaperTrading() {
  // ── Holdings state ──
  const [holdings, setHoldings] = useState<PaperHolding[]>([]);
  const [holdingNames, setHoldingNames] = useState<Record<string, string>>({});
  const [newSymbol, setNewSymbol] = useState("");
  const [newMarket, setNewMarket] = useState<"us" | "hk">("hk");
  const [quickQuotes, setQuickQuotes] = useState<{ hk: WatchlistQuote[]; us: WatchlistQuote[] }>({ hk: [], us: [] });
  const [quickLoading, setQuickLoading] = useState(false);

  // ── Strategy state ──
  const [strategy, setStrategy] = useState<StrategyName>("buy_and_hold");
  const [dcaFrequency, setDcaFrequency] = useState("monthly");
  const [gridCount, setGridCount] = useState(5);

  // ── Config state ──
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2025-01-01");
  const [initialUsd, setInitialUsd] = useState(100000);
  const [initialHkd, setInitialHkd] = useState(1000000);

  // ── Run state ──
  const [runs, setRuns] = useState<PaperTradingRun[]>([]);
  const [activeRun, setActiveRun] = useState<PaperTradingRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [optimalProgress, setOptimalProgress] = useState("");
  const [optimalRuns, setOptimalRuns] = useState<PaperTradingRun[]>([]);
  const [optimalBestRunId, setOptimalBestRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load history on mount ──
  useEffect(() => {
    api.listPaperTradingRuns()
      .then((res) => setRuns(res.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadQuickQuotes = async () => {
      setQuickLoading(true);
      try {
        const [hkCodesRes, usCodesRes] = await Promise.all([
          api.getWatchlistCodes("hk").catch(() => ({ codes: loadWatchlistCodes("hk") })),
          api.getWatchlistCodes("us").catch(() => ({ codes: loadWatchlistCodes("us") })),
        ]);
        const hkCodes = hkCodesRes.codes.length ? hkCodesRes.codes : loadWatchlistCodes("hk");
        const usCodes = usCodesRes.codes.length ? usCodesRes.codes : loadWatchlistCodes("us");
        const [hkQuotes, usQuotes] = await Promise.all([
          hkCodes.length ? api.getWatchlistQuote(hkCodes, "hk").catch(() => [] as WatchlistQuote[]) : Promise.resolve([]),
          usCodes.length ? api.getWatchlistQuote(usCodes, "us").catch(() => [] as WatchlistQuote[]) : Promise.resolve([]),
        ]);
        if (!cancelled) setQuickQuotes({ hk: hkQuotes, us: usQuotes });
      } finally {
        if (!cancelled) setQuickLoading(false);
      }
    };
    loadQuickQuotes();
    const id = setInterval(loadQuickQuotes, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // ── Polling for active run ──
  const pollRun = useCallback((runId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const run = await api.getPaperTradingRun(runId);
        setActiveRun(run);
        if (run.status === "completed" || run.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          api.listPaperTradingRuns().then((res) => setRuns(res.items)).catch(() => {});
        }
      } catch { /* ignore */ }
    }, 1500);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // ── Add holding ──
  const addHoldingToPortfolio = (symbol: string, market: "us" | "hk", name?: string) => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    if (holdings.some((h) => h.symbol.toUpperCase() === sym && h.market === market)) return;
    const equalPct = Math.round(10000 / (holdings.length + 1)) / 100;
    const updated = holdings.map((h) => ({ ...h, allocation_pct: equalPct }));
    updated.push({ symbol: sym, market, allocation_pct: equalPct });
    // adjust last to make sum = 100
    const sum = updated.reduce((s, h) => s + h.allocation_pct, 0);
    updated[updated.length - 1].allocation_pct = Math.round((updated[updated.length - 1].allocation_pct + (100 - sum)) * 100) / 100;
    setHoldings(updated);
    if (name && name !== sym) {
      setHoldingNames((prev) => ({ ...prev, [holdingKey(sym, market)]: name }));
    }
    setNewSymbol("");
  };

  const addHolding = async () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    if (holdings.some((h) => h.symbol.toUpperCase() === sym && h.market === newMarket)) return;
    try {
      const [quote] = await api.getWatchlistQuote([sym], newMarket);
      addHoldingToPortfolio(sym, newMarket, quote?.name);
    } catch {
      addHoldingToPortfolio(sym, newMarket);
    }
  };

  const addQuickQuote = (quote: WatchlistQuote, market: "hk" | "us") => {
    addHoldingToPortfolio(quote.code, market, quote.name);
  };

  const removeHolding = (idx: number) => {
    const removed = holdings[idx];
    const next = holdings.filter((_, i) => i !== idx);
    if (next.length > 0) {
      const equalPct = Math.round(10000 / next.length) / 100;
      next.forEach((h) => { h.allocation_pct = equalPct; });
      const sum = next.reduce((s, h) => s + h.allocation_pct, 0);
      next[next.length - 1].allocation_pct = Math.round((next[next.length - 1].allocation_pct + (100 - sum)) * 100) / 100;
    }
    setHoldings(next);
    if (removed) {
      setHoldingNames((prev) => {
        const copy = { ...prev };
        delete copy[holdingKey(removed.symbol, removed.market)];
        return copy;
      });
    }
  };

  const updateAllocation = (idx: number, val: number) => {
    const next = [...holdings];
    next[idx] = { ...next[idx], allocation_pct: val };
    setHoldings(next);
  };

  const totalAlloc = holdings.reduce((s, h) => s + h.allocation_pct, 0);
  const allocValid = Math.abs(totalAlloc - 100) < 0.02;

  // ── Submit ──
  const handleSubmit = async () => {
    if (holdings.length === 0 || !allocValid) return;
    setSubmitting(true);
    setError(null);
    setActiveRun(null);

    const params: Record<string, unknown> = {};
    Object.assign(params, strategyParamsFor(strategy, dcaFrequency, gridCount));

    try {
      const run = await api.createPaperTradingRun({
        holdings,
        strategy: { name: strategy, params } as PaperStrategyConfig,
        start_date: startDate,
        end_date: endDate,
        initial_usd: initialUsd,
        initial_hkd: initialHkd,
      });
      setActiveRun(run);
      pollRun(run.run_id);
    } catch (e: any) {
      setError(e?.message || "创建回测失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleOptimizeStrategies = async () => {
    if (holdings.length === 0 || !allocValid) return;
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    setOptimizing(true);
    setError(null);
    setActiveRun(null);
    setOptimalRuns([]);
    setOptimalBestRunId(null);
    setOptimalProgress(`正在创建 ${STRATEGY_OPTIONS.length} 个策略回测…`);

    try {
      const created = await Promise.all(
        STRATEGY_OPTIONS.map((option) => api.createPaperTradingRun({
          title: `最优策略候选 - ${option.label}`,
          holdings,
          strategy: {
            name: option.value,
            params: strategyParamsFor(option.value, dcaFrequency, gridCount),
          } as PaperStrategyConfig,
          start_date: startDate,
          end_date: endDate,
          initial_usd: initialUsd,
          initial_hkd: initialHkd,
        })),
      );

      const runIds = created.map((run) => run.run_id);
      const latestById = new Map(created.map((run) => [run.run_id, run]));
      const deadline = Date.now() + 20 * 60 * 1000;

      while (Date.now() < deadline) {
        const latest = await Promise.all(runIds.map((runId) => api.getPaperTradingRun(runId)));
        latest.forEach((run) => latestById.set(run.run_id, run));
        const finished = latest.filter((run) => run.status === "completed" || run.status === "failed").length;
        setOptimalRuns(latest);
        setOptimalProgress(`最优策略回测中：${finished}/${latest.length} 已完成`);
        if (finished === latest.length) break;
        await delay(1500);
      }

      const finalRuns = Array.from(latestById.values());
      const unfinished = finalRuns.filter((run) => run.status !== "completed" && run.status !== "failed");
      if (unfinished.length > 0) {
        throw new Error(`最优策略回测超时，仍有 ${unfinished.length} 个策略未完成`);
      }

      const completed = finalRuns.filter((run) => run.status === "completed" && run.metrics);
      if (completed.length === 0) {
        const failed = finalRuns.find((run) => run.status === "failed");
        throw new Error(failed?.error || "所有策略都未能完成回测");
      }

      const best = [...completed].sort(compareRuns)[0];
      setOptimalRuns(finalRuns);
      setOptimalBestRunId(best.run_id);
      setActiveRun(best);
      setStrategy(best.strategy.name as StrategyName);
      setOptimalProgress(`最优策略：${STRATEGY_LABELS[best.strategy.name as StrategyName] || best.strategy.name}`);
      api.listPaperTradingRuns().then((res) => setRuns(res.items)).catch(() => {});
    } catch (e: any) {
      setError(e?.message || "最优策略回测失败");
    } finally {
      setOptimizing(false);
    }
  };

  // ── Load a historical run ──
  const loadRun = async (runId: string) => {
    try {
      const run = await api.getPaperTradingRun(runId);
      setActiveRun(run);
    } catch { /* ignore */ }
  };

  const deleteRun = async (runId: string) => {
    try {
      await api.deletePaperTradingRun(runId);
      setRuns((prev) => prev.filter((r) => r.run_id !== runId));
      if (activeRun?.run_id === runId) setActiveRun(null);
    } catch { /* ignore */ }
  };

  const m = activeRun?.metrics;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Briefcase className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-bold">模拟盘 · 历史回测</h1>
      </div>

      <div className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">自选快捷添加</h2>
          {quickLoading && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              更新中
            </span>
          )}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <WatchlistQuickAdd
            title="港股自选"
            market="hk"
            quotes={quickQuotes.hk}
            holdings={holdings}
            onAdd={addQuickQuote}
          />
          <WatchlistQuickAdd
            title="美股自选"
            market="us"
            quotes={quickQuotes.us}
            holdings={holdings}
            onAdd={addQuickQuote}
          />
        </div>
      </div>

      {/* ── Configuration Section ── */}
      <div className="space-y-4 rounded-xl border bg-card p-4">
        <h2 className="text-sm font-semibold">投资组合</h2>

        {/* Add holding */}
        <div className="flex items-center gap-2">
          <select
            value={newMarket}
            onChange={(e) => setNewMarket(e.target.value as "us" | "hk")}
            className="rounded-lg border bg-background px-2 py-1.5 text-sm"
          >
            <option value="us">美股</option>
            <option value="hk">港股</option>
          </select>
          <input
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void addHolding();
            }}
            placeholder={newMarket === "us" ? "输入代码 如 AAPL" : "输入代码 如 0700"}
            className="flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => void addHolding()}
            className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-3.5 w-3.5" /> 添加
          </button>
          <button
            onClick={() => {
              if (holdings.some((h) => h.symbol === "CASH" && h.market === "us")) return;
              const equalPct = Math.round(10000 / (holdings.length + 1)) / 100;
              const updated = holdings.map((h) => ({ ...h, allocation_pct: equalPct }));
              updated.push({ symbol: "CASH", market: "us" as const, allocation_pct: equalPct });
              const sum = updated.reduce((s, h) => s + h.allocation_pct, 0);
              updated[updated.length - 1].allocation_pct = Math.round((updated[updated.length - 1].allocation_pct + (100 - sum)) * 100) / 100;
              setHoldings(updated);
            }}
            disabled={holdings.some((h) => h.symbol === "CASH")}
            className="flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-40"
          >
            💵 现金
          </button>
        </div>

        {/* Holdings table */}
        {holdings.length > 0 && (
          <div className="rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">公司</th>
                  <th className="px-3 py-2 text-left font-medium">市场</th>
                  <th className="px-3 py-2 text-left font-medium">占比 %</th>
                  <th className="px-3 py-2 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((h, i) => (
                  <tr key={`${h.symbol}-${h.market}`} className="border-b last:border-0">
                    <td className="px-3 py-2 font-mono">{h.symbol === "CASH" ? "💵 现金" : h.symbol}</td>
                    <td className="px-3 py-2">
                      {h.symbol === "CASH" ? "现金" : holdingNames[holdingKey(h.symbol, h.market)] || "—"}
                    </td>
                    <td className="px-3 py-2">{h.symbol === "CASH" ? "—" : h.market === "us" ? "美股" : "港股"}</td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={0.01}
                        value={h.allocation_pct}
                        onChange={(e) => updateAllocation(i, parseFloat(e.target.value) || 0)}
                        className="w-20 rounded border bg-background px-2 py-0.5 text-sm tabular-nums"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <button onClick={() => removeHolding(i)} className="text-muted-foreground hover:text-red-500">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className={cn("px-3 py-1.5 text-xs", allocValid ? "text-muted-foreground" : "text-red-500 font-medium")}>
              合计: {totalAlloc.toFixed(2)}%{!allocValid && " — 必须等于 100%"}
            </div>
          </div>
        )}

        {/* Strategy selector */}
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">策略</h2>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {STRATEGY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setStrategy(opt.value)}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                  strategy === opt.value
                    ? "border-primary bg-primary/10 text-primary"
                    : "hover:border-primary/50",
                )}
              >
                <p className="font-medium">{opt.label}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">{opt.desc}</p>
              </button>
            ))}
          </div>

          {/* Strategy params */}
          {(strategy === "dca" || strategy === "smart_dca") && (
            <div className="flex items-center gap-3 pl-1">
              <label className="text-xs text-muted-foreground">
                {strategy === "smart_dca" ? "智能定投频率" : "定投频率"}
              </label>
              <select
                value={dcaFrequency}
                onChange={(e) => setDcaFrequency(e.target.value)}
                className="rounded-lg border bg-background px-2 py-1 text-sm"
              >
                <option value="weekly">每周</option>
                <option value="biweekly">每两周</option>
                <option value="monthly">每月</option>
              </select>
            </div>
          )}
          {strategy === "grid" && (
            <div className="flex items-center gap-3 pl-1">
              <label className="text-xs text-muted-foreground">网格数量</label>
              <input
                type="number"
                min={2}
                max={50}
                value={gridCount}
                onChange={(e) => setGridCount(parseInt(e.target.value) || 5)}
                className="w-20 rounded-lg border bg-background px-2 py-1 text-sm"
              />
              <span className="text-[11px] text-muted-foreground">（自动根据历史价格确定上下限）</span>
            </div>
          )}
        </div>

        {/* Date range & capital */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-muted-foreground">开始日期</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 w-full rounded-lg border bg-background px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">结束日期</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 w-full rounded-lg border bg-background px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">美元资金 (USD)</label>
            <input
              type="number"
              min={0}
              value={initialUsd}
              onChange={(e) => setInitialUsd(parseFloat(e.target.value) || 0)}
              className="mt-1 w-full rounded-lg border bg-background px-2 py-1.5 text-sm tabular-nums"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">港币资金 (HKD)</label>
            <input
              type="number"
              min={0}
              value={initialHkd}
              onChange={(e) => setInitialHkd(parseFloat(e.target.value) || 0)}
              className="mt-1 w-full rounded-lg border bg-background px-2 py-1.5 text-sm tabular-nums"
            />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            总资金 ≈ ${(initialUsd + initialHkd / 7.8).toLocaleString(undefined, { maximumFractionDigits: 0 })} USD
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={handleOptimizeStrategies}
              disabled={submitting || optimizing || holdings.length === 0 || !allocValid}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
                submitting || optimizing || holdings.length === 0 || !allocValid
                  ? "cursor-not-allowed bg-muted text-muted-foreground"
                  : "bg-background hover:bg-accent",
              )}
            >
              {optimizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              最优策略
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting || optimizing || holdings.length === 0 || !allocValid}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                submitting || optimizing || holdings.length === 0 || !allocValid
                  ? "bg-muted text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              运行回测
            </button>
          </div>
        </div>

        {optimalProgress && <p className="text-xs text-muted-foreground">{optimalProgress}</p>}
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>

      {optimalRuns.length > 0 && (
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">最优策略对比</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                排序规则：夏普比率优先，其次总收益，其次最大亏损更小
              </p>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">策略</th>
                  <th className="px-3 py-2 text-right font-medium">总收益</th>
                  <th className="px-3 py-2 text-right font-medium">夏普</th>
                  <th className="px-3 py-2 text-right font-medium">最大亏损</th>
                  <th className="px-3 py-2 text-right font-medium">交易数</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                </tr>
              </thead>
              <tbody>
                {[...optimalRuns].sort((a, b) => {
                  if (a.status !== "completed" || !a.metrics) return 1;
                  if (b.status !== "completed" || !b.metrics) return -1;
                  return compareRuns(a, b);
                }).map((run) => {
                  const metrics = run.metrics ?? {};
                  const isBest = run.run_id === optimalBestRunId;
                  return (
                    <tr
                      key={run.run_id}
                      className={cn("border-b last:border-0 hover:bg-muted/30", isBest && "bg-primary/10")}
                    >
                      <td className="px-3 py-2 font-medium">
                        <button onClick={() => setActiveRun(run)} className="text-left hover:text-primary">
                          {STRATEGY_LABELS[run.strategy.name as StrategyName] || run.strategy.name}
                          {isBest && <span className="ml-2 text-primary">最优</span>}
                        </button>
                      </td>
                      <td className={cn("px-3 py-2 text-right tabular-nums", finiteNumber(metrics.total_return) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                        {run.status === "completed" ? pct(metrics.total_return as number) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {run.status === "completed" ? finiteNumber(metrics.sharpe).toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-red-500">
                        {run.status === "completed" ? pct(metrics.max_drawdown as number) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {run.status === "completed" ? String(metrics.trade_count ?? run.trades?.length ?? 0) : "—"}
                      </td>
                      <td className={cn(
                        "px-3 py-2",
                        run.status === "completed" ? "text-emerald-600 dark:text-emerald-400" : run.status === "failed" ? "text-red-500" : "text-yellow-500",
                      )}>
                        {run.status === "failed" ? `失败：${run.error || "未知错误"}` : run.status}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Results Section ── */}
      {activeRun && (
        <div className="space-y-4">
          {/* Status */}
          {(activeRun.status === "queued" || activeRun.status === "running") && (
            <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-6 justify-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">回测运行中…</span>
            </div>
          )}

          {activeRun.status === "failed" && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-500">
              回测失败: {activeRun.error}
            </div>
          )}

          {activeRun.status === "completed" && m && (
            <>
              {/* Metrics grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
                <Stat
                  label="总收益"
                  value={pct(m.total_return as number)}
                  tone={(m.total_return as number) > 0 ? "good" : "bad"}
                />
                <Stat
                  label="年化收益"
                  value={pct(m.annual_return as number)}
                  tone={(m.annual_return as number) > 0 ? "good" : "bad"}
                />
                <Stat
                  label="夏普比率"
                  value={(m.sharpe as number)?.toFixed(2) ?? "—"}
                  tone={(m.sharpe as number) > 1 ? "good" : (m.sharpe as number) < 0 ? "bad" : "neutral"}
                />
                <Stat
                  label="最大亏损"
                  value={pct(m.max_drawdown as number)}
                  tone="bad"
                />
                <Stat
                  label="胜率"
                  value={pct(m.win_rate as number)}
                  tone={(m.win_rate as number) > 0.5 ? "good" : "neutral"}
                />
                <Stat
                  label="交易次数"
                  value={String(m.trade_count ?? activeRun.trades?.length ?? 0)}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Stat label="初始资金" value={fmtMoney(activeRun.initial_total_usd)} />
                <Stat
                  label="最终净值"
                  value={fmtMoney(m.final_value as number)}
                  tone={(m.final_value as number) > activeRun.initial_total_usd ? "good" : "bad"}
                />
                <Stat label="Sortino" value={(m.sortino as number)?.toFixed(2) ?? "—"} />
                <Stat label="Calmar" value={(m.calmar as number)?.toFixed(2) ?? "—"} />
              </div>

              {/* Equity curve */}
              {activeRun.equity_curve && activeRun.equity_curve.length > 0 && (
                <div className="rounded-xl border bg-card p-4">
                  <h3 className="text-sm font-semibold mb-3">组合走势</h3>
                  <PaperEquityChart data={activeRun.equity_curve} trades={activeRun.trades} height={300} />
                </div>
              )}

              {/* Per-symbol stats */}
              {m.by_symbol && typeof m.by_symbol === "object" && Object.keys(m.by_symbol as Record<string, unknown>).length > 0 && (
                <div className="rounded-xl border bg-card p-4">
                  <h3 className="text-sm font-semibold mb-2">分标的统计</h3>
                  <div className="rounded-lg border">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-muted-foreground">
                          <th className="px-3 py-2 text-left font-medium">标的</th>
                          <th className="px-3 py-2 text-right font-medium">交易数</th>
                          <th className="px-3 py-2 text-right font-medium">胜率</th>
                          <th className="px-3 py-2 text-right font-medium">总盈亏</th>
                          <th className="px-3 py-2 text-right font-medium">平均盈亏</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(m.by_symbol as Record<string, any>).map(([sym, stats]) => (
                          <tr key={sym} className="border-b last:border-0">
                            <td className="px-3 py-2 font-mono">{sym}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{stats.count}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{pct(stats.win_rate)}</td>
                            <td className={cn("px-3 py-2 text-right tabular-nums", stats.total_pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                              ${stats.total_pnl?.toLocaleString()}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">${stats.avg_pnl?.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Trade log */}
              {activeRun.trades && activeRun.trades.length > 0 && (
                <div className="rounded-xl border bg-card p-4">
                  <h3 className="text-sm font-semibold mb-2">交易明细 ({activeRun.trades.length} 笔)</h3>
                  <div className="max-h-64 overflow-y-auto rounded-lg border">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-card">
                        <tr className="border-b text-muted-foreground">
                          <th className="px-2 py-1.5 text-left font-medium">标的</th>
                          <th className="px-2 py-1.5 text-left font-medium">方向</th>
                          <th className="px-2 py-1.5 text-right font-medium">买入价</th>
                          <th className="px-2 py-1.5 text-right font-medium">卖出价</th>
                          <th className="px-2 py-1.5 text-left font-medium">买入日</th>
                          <th className="px-2 py-1.5 text-left font-medium">卖出日</th>
                          <th className="px-2 py-1.5 text-right font-medium">数量</th>
                          <th className="px-2 py-1.5 text-right font-medium">盈亏</th>
                          <th className="px-2 py-1.5 text-right font-medium">盈亏%</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeRun.trades.map((t: PaperTrade, i: number) => (
                          <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                            <td className="px-2 py-1.5 font-mono">{t.symbol}</td>
                            <td className="px-2 py-1.5">{t.direction === 1 ? "做多" : "做空"}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{t.entry_price.toFixed(2)}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{t.exit_price.toFixed(2)}</td>
                            <td className="px-2 py-1.5">{t.entry_time}</td>
                            <td className="px-2 py-1.5">{t.exit_time}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{t.size.toFixed(2)}</td>
                            <td className={cn("px-2 py-1.5 text-right tabular-nums", t.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                              ${t.pnl.toLocaleString()}
                            </td>
                            <td className={cn("px-2 py-1.5 text-right tabular-nums", t.pnl_pct >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                              {t.pnl_pct.toFixed(2)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── History Section ── */}
      {runs.length > 0 && (
        <div className="rounded-xl border bg-card p-4">
          <button
            onClick={() => setHistoryOpen(!historyOpen)}
            className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground transition-colors"
          >
            {historyOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            历史回测 ({runs.length})
          </button>
          {historyOpen && (
            <div className="mt-3 space-y-1">
              {runs.map((r) => (
                <div
                  key={r.run_id}
                  className={cn(
                    "flex items-center justify-between rounded-lg px-3 py-2 text-sm cursor-pointer hover:bg-muted/50 transition-colors",
                    activeRun?.run_id === r.run_id && "bg-muted/50",
                  )}
                >
                  <button onClick={() => loadRun(r.run_id)} className="flex-1 text-left">
                    <span className="font-medium">{r.title || r.strategy.name}</span>
                    <span className="text-muted-foreground ml-2">{r.start_date} → {r.end_date}</span>
                    <span className={cn(
                      "ml-2 text-xs",
                      r.status === "completed" ? "text-emerald-500" : r.status === "failed" ? "text-red-500" : "text-yellow-500",
                    )}>
                      {r.status}
                    </span>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteRun(r.run_id); }}
                    className="text-muted-foreground hover:text-red-500 ml-2"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
