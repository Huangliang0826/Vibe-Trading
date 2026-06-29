import { useEffect, useState, useCallback, useMemo } from "react";
import { LineChart, Loader2, AlertTriangle, TrendingUp } from "lucide-react";
import { api, type WatchlistMarket, type ForecastResponse, type HSTechBestStrategyResponse, type TradeSignal } from "@/lib/api";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { cn } from "@/lib/utils";

function loadList(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}

type WatchlistItem = { market: WatchlistMarket; code: string };
type BestStrategyState = {
  data: HSTechBestStrategyResponse | null;
  loading: boolean;
  error: string | null;
};
type RecentStrategySignal = {
  key: string;
  market: WatchlistMarket;
  code: string;
  name: string;
  strategyLabel: string;
  action: "开仓" | "平仓";
  date: string;
  price: number;
  pnlPct?: number;
};

function stockKey(market: WatchlistMarket, code: string): string {
  return `${market}:${code.toUpperCase()}`;
}

function forecastCardId(market: WatchlistMarket, code: string): string {
  return `forecast-card-${market}-${code.toUpperCase()}`;
}

function scrollToForecastCard(market: WatchlistMarket, code: string) {
  const el = document.getElementById(forecastCardId(market, code));
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function daysAgoISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function recentSignalsFromBestStrategies(
  items: WatchlistItem[],
  states: Record<string, BestStrategyState>,
  sinceISO: string,
): RecentStrategySignal[] {
  const signals: RecentStrategySignal[] = [];
  for (const item of items) {
    const key = stockKey(item.market, item.code);
    const run = states[key]?.data;
    const trades = run?.best?.trades || [];
    const strategyLabel = run?.best?.strategy?.label || run?.best?.strategy?.name || "最优策略";
    for (const trade of trades as TradeSignal[]) {
      if (trade.entry_date >= sinceISO) {
        signals.push({
          key: `${key}:entry:${trade.entry_date}`,
          market: item.market,
          code: item.code,
          name: run?.name || item.code,
          strategyLabel,
          action: "开仓",
          date: trade.entry_date,
          price: trade.entry_price,
        });
      }
      if (trade.exit_date >= sinceISO) {
        signals.push({
          key: `${key}:exit:${trade.exit_date}`,
          market: item.market,
          code: item.code,
          name: run?.name || item.code,
          strategyLabel,
          action: "平仓",
          date: trade.exit_date,
          price: trade.exit_price,
          pnlPct: trade.pnl_pct,
        });
      }
    }
  }
  const latestByStock = new Map<string, RecentStrategySignal>();
  for (const signal of signals.sort((a, b) => b.date.localeCompare(a.date))) {
    const key = stockKey(signal.market, signal.code);
    if (!latestByStock.has(key)) {
      latestByStock.set(key, signal);
    }
  }
  return [...latestByStock.values()];
}

function fmtRet(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function RecentSignalsPanel({
  signals,
  loadingCount,
  errorCount,
}: {
  signals: RecentStrategySignal[];
  loadingCount: number;
  errorCount: number;
}) {
  if (!signals.length && loadingCount === 0 && errorCount === 0) return null;
  return (
    <div className="rounded-2xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-foreground">最近 7 天策略信号</h2>
          <p className="text-[11px] text-muted-foreground">来自每只自选股的模拟盘最优策略，结果每日自动缓存</p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {loadingCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1">
              <Loader2 className="h-3 w-3 animate-spin" /> 检查 {loadingCount} 只
            </span>
          )}
          {errorCount > 0 && <span className="rounded-md border px-2 py-1 text-red-500">{errorCount} 只失败</span>}
        </div>
      </div>
      {signals.length > 0 ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {signals.map((signal) => (
            <div key={signal.key} className="rounded-lg border bg-background px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">
                    {signal.name}
                    <span className="ml-1 font-mono text-xs text-muted-foreground">{signal.code}</span>
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {signal.strategyLabel} · {signal.date}
                  </p>
                </div>
                <span className={cn(
                  "shrink-0 rounded-md px-2 py-1 text-xs font-medium",
                  signal.action === "开仓"
                    ? "bg-red-500/10 text-red-600 dark:text-red-400"
                    : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
                )}>
                  {signal.action}
                </span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground tabular-nums">
                价格 {signal.price.toFixed(2)}
                {signal.pnlPct != null && <span className="ml-2">盈亏 {fmtRet(signal.pnlPct / 100)}</span>}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">最近 7 天暂无开仓或平仓信号。</p>
      )}
    </div>
  );
}

function ForecastWatchlistLinks({
  items,
  states,
}: {
  items: WatchlistItem[];
  states: Record<string, BestStrategyState>;
}) {
  if (!items.length) return null;
  return (
    <div className="rounded-2xl border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">自选股</h2>
          <p className="text-[11px] text-muted-foreground">点击股票名称跳转到对应预测图表</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => {
          const state = states[stockKey(item.market, item.code)];
          const name = state?.data?.name && state.data.name !== item.code ? state.data.name : item.code;
          return (
            <button
              key={stockKey(item.market, item.code)}
              onClick={() => scrollToForecastCard(item.market, item.code)}
              className="rounded-lg border bg-background px-3 py-2 text-left transition hover:border-foreground/30 hover:bg-muted"
            >
              <span className="block max-w-36 truncate text-sm font-medium text-foreground">{name}</span>
              <span className="font-mono text-[11px] uppercase text-muted-foreground">{item.code}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── per-stock card ───────────────────────────────────────────────────────────

function ForecastCard({
  market,
  code,
  context,
  displayHistory,
  bestStrategyState,
  onRefreshBestStrategy,
}: {
  market: WatchlistMarket;
  code: string;
  context: number;
  displayHistory: number;
  bestStrategyState?: BestStrategyState;
  onRefreshBestStrategy: (market: WatchlistMarket, code: string, refresh?: boolean) => void;
}) {
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const bestStrategy = bestStrategyState?.data || null;
  const bestStrategyLoading = !!bestStrategyState?.loading;
  const bestStrategyError = bestStrategyState?.error || null;
  const trades = bestStrategy?.best?.trades || [];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getForecast(market, code, 3, context, 0, displayHistory)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e?.message || "预测失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [market, code, context, displayHistory]);

  return (
    <div id={forecastCardId(market, code)} className="scroll-mt-24 rounded-2xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-foreground">{data?.name && data.name !== code ? data.name : code}</span>
          <span className="font-mono text-xs text-muted-foreground">{code}</span>
          <span className="text-[10px] uppercase text-muted-foreground/60">{market}</span>
          {data?.context_used != null && (
            <span className="text-[10px] text-muted-foreground/60">· 输入 {data.context_used} 日历史</span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {bestStrategy?.best?.metrics && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                总收益 {fmtRet(bestStrategy.best.metrics.total_return as number)}
              </span>
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                最大亏损 {fmtRet(bestStrategy.best.metrics.max_drawdown as number)}
              </span>
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                夏普 {Number(bestStrategy.best.metrics.sharpe ?? 0).toFixed(2)}
              </span>
            </div>
          )}
          <button
            onClick={() => onRefreshBestStrategy(market, code, true)}
            disabled={bestStrategyLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-foreground/30 hover:text-foreground disabled:opacity-50"
            title={bestStrategy?.best?.strategy?.label ? `当前最优：${bestStrategy.best.strategy.label}` : "运行模拟盘策略池，刷新最优买卖信号"}
          >
            {bestStrategyLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TrendingUp className="h-3.5 w-3.5" />}
            {bestStrategyLoading ? "策略回测中" : bestStrategy?.best?.strategy?.label ? `最优：${bestStrategy.best.strategy.label}` : "最优策略"}
          </button>
          {data && !data.model && (
            <span className="text-[10px] text-yellow-600 dark:text-yellow-400">
              {data.model_error === "timesfm_not_installed" ? "模型未安装，仅显示基线" : "模型不可用"}
            </span>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground" style={{ height: 320 }}>
          <Loader2 className="h-5 w-5 animate-spin" /> 预测计算中…（首次加载模型较慢）
        </div>
      ) : error ? (
        <div className="flex items-center justify-center gap-2 text-sm text-red-500" style={{ height: 320 }}>
          <AlertTriangle className="h-4 w-4" /> {error}
        </div>
      ) : data ? (
        <>
          <ForecastChart data={data} trades={trades.length > 0 ? trades : undefined} />
          {(bestStrategy || bestStrategyError || bestStrategyLoading) && (
            <div className="mt-3 rounded-lg border bg-muted/25 px-3 py-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-medium text-foreground">AI 总结 · 模拟盘最优策略</p>
                  {bestStrategy?.best?.metrics && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {bestStrategy.best.strategy.label || bestStrategy.best.strategy.name}
                      <span className="mx-1">·</span>
                      总收益 {fmtRet(bestStrategy.best.metrics.total_return as number)}
                      <span className="mx-1">·</span>
                      最大亏损 {fmtRet(bestStrategy.best.metrics.max_drawdown as number)}
                      <span className="mx-1">·</span>
                      夏普 {Number(bestStrategy.best.metrics.sharpe ?? 0).toFixed(2)}
                    </p>
                  )}
                </div>
                {bestStrategy?.cached && <span className="text-[10px] text-muted-foreground">24小时缓存</span>}
              </div>
              {bestStrategyLoading ? (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在运行模拟盘策略池…
                </p>
              ) : bestStrategyError ? (
                <p className="mt-2 text-xs text-red-500">{bestStrategyError}</p>
              ) : bestStrategy?.summary ? (
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{bestStrategy.summary}</p>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────

const CONTEXT_OPTIONS: { label: string; value: number; displayHistory: number }[] = [
  { label: "全部历史", value: 0, displayHistory: 0 },
  { label: "5 年", value: 1260, displayHistory: 1260 },
  { label: "2 年", value: 512, displayHistory: 512 },
  { label: "1 年", value: 252, displayHistory: 252 },
];

export function Forecast() {
  const [hk, setHk] = useState<string[]>([]);
  const [us, setUs] = useState<string[]>([]);
  const [cnList, setCnList] = useState<string[]>([]);
  const [context, setContext] = useState(1260); // 默认 5 年：更适合观察中长期走势和策略信号
  const [bestByKey, setBestByKey] = useState<Record<string, BestStrategyState>>({});
  const selectedContext = CONTEXT_OPTIONS.find((option) => option.value === context) || CONTEXT_OPTIONS[2];

  const sync = useCallback(() => {
    setHk(loadList("watchlist-hk"));
    setUs(loadList("watchlist-us"));
    setCnList(loadList("watchlist-cn"));
  }, []);

  useEffect(() => {
    sync();
    // Re-sync when returning to the tab (watchlist edited on 总览).
    window.addEventListener("focus", sync);
    return () => window.removeEventListener("focus", sync);
  }, [sync]);

  const total = hk.length + us.length + cnList.length;
  const watchlistItems = useMemo<WatchlistItem[]>(() => [
    ...cnList.map((code) => ({ market: "cn" as const, code: code.toUpperCase() })),
    ...hk.map((code) => ({ market: "hk" as const, code: code.toUpperCase() })),
    ...us.map((code) => ({ market: "us" as const, code: code.toUpperCase() })),
  ], [hk, us, cnList]);
  const loadBestStrategy = useCallback((market: WatchlistMarket, code: string, refresh = false) => {
    const key = stockKey(market, code);
    setBestByKey((prev) => ({
      ...prev,
      [key]: { data: prev[key]?.data || null, loading: true, error: null },
    }));
    api.getForecastBestPaperStrategy(market, code, refresh)
      .then((data) => {
        setBestByKey((prev) => ({ ...prev, [key]: { data, loading: false, error: null } }));
      })
      .catch((e) => {
        setBestByKey((prev) => ({
          ...prev,
          [key]: { data: prev[key]?.data || null, loading: false, error: e?.message || "最优策略回测失败" },
        }));
      });
  }, []);

  useEffect(() => {
    for (const item of watchlistItems) {
      const key = stockKey(item.market, item.code);
      if (!bestByKey[key]) {
        loadBestStrategy(item.market, item.code, false);
      }
    }
  }, [watchlistItems, bestByKey, loadBestStrategy]);

  const recentSignals = useMemo(
    () => recentSignalsFromBestStrategies(watchlistItems, bestByKey, daysAgoISO(7)),
    [watchlistItems, bestByKey],
  );
  const bestLoadingCount = watchlistItems.filter((item) => bestByKey[stockKey(item.market, item.code)]?.loading).length;
  const bestErrorCount = watchlistItems.filter((item) => bestByKey[stockKey(item.market, item.code)]?.error).length;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-3">
          <LineChart className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold">走势预测</h1>
            <p className="text-xs text-muted-foreground">TimesFM 3 个月不确定性锥 · 同步总览自选股</p>
          </div>
        </div>
        {/* Context length — the same knob drives both forecast and backtest. */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">历史范围</span>
          <div className="flex gap-1">
            {CONTEXT_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setContext(o.value)}
                className={cn(
                  "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                  o.value === context
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted border border-border"
                )}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {total === 0 ? (
        <div className="rounded-2xl border border-dashed bg-card/50 py-12 flex flex-col items-center gap-2 text-center">
          <LineChart className="h-7 w-7 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">在「总览」页添加A股/港股/美股自选后，此处显示走势预测</p>
        </div>
      ) : (
        <div className="space-y-4">
          <RecentSignalsPanel signals={recentSignals} loadingCount={bestLoadingCount} errorCount={bestErrorCount} />
          <ForecastWatchlistLinks items={watchlistItems} states={bestByKey} />
          {watchlistItems.map((item) => (
            <ForecastCard
              key={`${item.market}-${item.code}-${context}`}
              market={item.market}
              code={item.code}
              context={context}
              displayHistory={selectedContext.displayHistory}
              bestStrategyState={bestByKey[stockKey(item.market, item.code)]}
              onRefreshBestStrategy={loadBestStrategy}
            />
          ))}
        </div>
      )}
    </div>
  );
}
