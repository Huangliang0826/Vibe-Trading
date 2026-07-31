import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { LineChart, Loader2, AlertTriangle, TrendingUp, RefreshCw } from "lucide-react";
import { api, type WatchlistMarket, type ForecastResponse, type HSTechBestStrategyResponse, type TradeSignal } from "@/lib/api";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { cn } from "@/lib/utils";
import {
  compactStrategyResponse,
  forecastSessionKey,
  readSessionCache,
  strategySessionKey,
  writeSessionCache,
} from "@/lib/forecast-session-cache";
import { analyticsSessionId, trackProductEvent } from "@/lib/analytics";

const FORECAST_SESSION_TTL = 48 * 60 * 60 * 1000;
const STRATEGY_SESSION_TTL = 24 * 60 * 60 * 1000;

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

// Per-stock manual strategy override, saved as the default for next time.
// Empty = follow the validated robust pick.
function strategyOverrideKey(market: WatchlistMarket, code: string): string {
  return `forecast-strategy:${stockKey(market, code)}`;
}
function savedStrategyOverride(market: WatchlistMarket, code: string): string {
  try { return localStorage.getItem(strategyOverrideKey(market, code)) || ""; } catch { return ""; }
}
function saveStrategyOverride(market: WatchlistMarket, code: string, strategy: string) {
  try {
    if (strategy) localStorage.setItem(strategyOverrideKey(market, code), strategy);
    else localStorage.removeItem(strategyOverrideKey(market, code));
  } catch { /* ignore */ }
}

function forecastCardId(market: WatchlistMarket, code: string): string {
  return `forecast-card-${market}-${code.toUpperCase()}`;
}

function scrollToForecastCard(market: WatchlistMarket, code: string) {
  const el = document.getElementById(forecastCardId(market, code));
  if (!el) return;
  // Instant (not smooth): forecast cards lazy-mount as they enter the viewport,
  // and the resulting layout shift cancels an in-flight smooth scroll, often
  // leaving the target off-screen. A second pass on the next frame corrects for
  // any height the newly mounted card added.
  el.scrollIntoView({ behavior: "auto", block: "center" });
  requestAnimationFrame(() => {
    document.getElementById(forecastCardId(market, code))
      ?.scrollIntoView({ behavior: "auto", block: "center" });
  });
}

function daysAgoISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function recentSignalsFromBestStrategies(
  items: WatchlistItem[],
  states: Record<string, BestStrategyState>,
  sinceISO: string,
): RecentStrategySignal[] {
  const signals: RecentStrategySignal[] = [];
  for (const item of items) {
    const key = stockKey(item.market, item.code);
    const run = states[key]?.data;
    if (run?.reliable === false) continue;
    const trades = run?.best?.trades || [];
    const strategyLabel = run?.best?.strategy?.label || run?.best?.strategy?.name || "最稳健策略";
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
      if (trade.exit_reason !== "end_of_backtest" && trade.exit_date >= sinceISO) {
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
  // Later events on the same date win (for example, rebalance exit then reopen).
  for (const signal of signals.sort((a, b) => a.date.localeCompare(b.date)).reverse()) {
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

export function formatHistoryDuration(startISO: string, endISO: string): string {
  const start = new Date(`${startISO}T00:00:00Z`);
  const end = new Date(`${endISO}T00:00:00Z`);
  const days = Math.max(0, (end.getTime() - start.getTime()) / 86_400_000);
  if (days >= 365.2425 * 2) {
    const roundedYears = Math.round((days / 365.2425) * 10) / 10;
    return `${Number.isInteger(roundedYears) ? roundedYears.toFixed(0) : roundedYears.toFixed(1)}年`;
  }
  const months = Math.max(
    0,
    (end.getUTCFullYear() - start.getUTCFullYear()) * 12
      + end.getUTCMonth() - start.getUTCMonth()
      - (end.getUTCDate() < start.getUTCDate() ? 1 : 0),
  );
  return months < 1 ? "不足1个月" : `${months}个月`;
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
    <div className="app-panel">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 className="app-panel-title">最近 7 天策略信号</h2>
          <p className="text-[11px] text-muted-foreground">来自每只自选股的多时间段稳健策略，年度选择、每日更新信号</p>
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
            <div
              key={signal.key}
              role="button"
              tabIndex={0}
              onClick={() => scrollToForecastCard(signal.market, signal.code)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  scrollToForecastCard(signal.market, signal.code);
                }
              }}
              title={`查看 ${signal.name} 的预测图表`}
              className="cursor-pointer rounded-2xl border bg-card px-3.5 py-3 transition hover:border-primary/40 hover:bg-muted/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-normal text-foreground">
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
    <div className="app-panel">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h2 className="app-panel-title">自选股</h2>
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
              className="soft-card-interactive rounded-2xl px-3.5 py-3 text-left"
            >
              <span className="block max-w-36 truncate text-sm font-normal text-foreground">{name}</span>
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
  onRefreshBestStrategy: (market: WatchlistMarket, code: string, refresh?: boolean, strategy?: string) => void;
}) {
  const cacheKey = forecastSessionKey(market, code, context, displayHistory);
  const initialCached = useRef(readSessionCache<ForecastResponse>(cacheKey, FORECAST_SESSION_TTL));
  const [data, setData] = useState<ForecastResponse | null>(initialCached.current);
  const [loading, setLoading] = useState(!initialCached.current);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bestStrategy = bestStrategyState?.data || null;
  const bestStrategyLoading = !!bestStrategyState?.loading;
  const bestStrategyError = bestStrategyState?.error || null;
  const trades = bestStrategy?.reliable === false ? [] : bestStrategy?.best?.trades || [];
  const oosMetrics = bestStrategy?.oos_validation?.metrics;
  const historyDuration = bestStrategy
    ? formatHistoryDuration(bestStrategy.start_date, bestStrategy.end_date)
    : "";

  // Strategy picker: robust pick vs the user's saved override, plus the menu.
  const robustRecommended = bestStrategy?.robust_recommended || bestStrategy?.best?.strategy?.name || "";
  const isUserSelected = !!bestStrategy?.user_selected;
  const activeStrategy = bestStrategy?.best?.strategy?.name || "";
  const sortedCandidates = (bestStrategy?.candidates || [])
    .filter((c) => c.status === "completed" && c.metrics)
    .sort((a, b) => (b.metrics?.total_return ?? -Infinity) - (a.metrics?.total_return ?? -Infinity));
  const pickStrategy = (name: string) => {
    const override = name === robustRecommended ? "" : name;
    saveStrategyOverride(market, code, override);
    onRefreshBestStrategy(market, code, false, override);
  };

  // ``nocache=1`` bypasses both the browser session cache and the backend's
  // 48h forecast cache so the cone is rebuilt from the latest available bars.
  const loadForecast = useCallback((nocache: 0 | 1) => {
    let cancelled = false;
    if (nocache) setRefreshing(true);
    else setLoading(!initialCached.current);
    setError(null);
    api.getForecast(market, code, 3, context, nocache, displayHistory)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          writeSessionCache(cacheKey, d);
        }
      })
      .catch((e) => {
        // Keep the stale cone visible on a background refresh failure.
        if (!cancelled && !(initialCached.current && !nocache)) setError(e?.message || "预测失败");
      })
      .finally(() => { if (!cancelled) { setLoading(false); setRefreshing(false); } });
    return () => { cancelled = true; };
  }, [market, code, context, displayHistory, cacheKey]);

  useEffect(() => loadForecast(0), [loadForecast]);

  // Self-heal a stale cone: if the strategy has a signal newer than the cone's
  // last bar (the two feeds cache independently), the newest entry/exit marker
  // would sit off the chart. Silently refetch the cone once with nocache so its
  // history catches up. Guarded by the cone's last date so it never loops.
  const autoRefreshedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!data || loading || refreshing) return;
    const hist = data.history || [];
    const lastHist = hist.length ? hist[hist.length - 1]?.date : "";
    if (!lastHist || !trades.length) return;
    const latestSignal = trades.reduce((max, t) => {
      const d = t.exit_reason === "end_of_backtest" ? t.entry_date : (t.exit_date || t.entry_date);
      return d && d > max ? d : max;
    }, "");
    if (latestSignal > lastHist && autoRefreshedForRef.current !== lastHist) {
      autoRefreshedForRef.current = lastHist;
      loadForecast(1);
    }
  }, [data, trades, loading, refreshing, loadForecast]);

  return (
    <div className="app-panel">
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-normal text-foreground">{data?.name && data.name !== code ? data.name : code}</span>
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
                总收益 {fmtRet(bestStrategy.best.metrics.total_return as number)}（{historyDuration}）
              </span>
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                最大亏损 {fmtRet(bestStrategy.best.metrics.max_loss as number | null | undefined)}
              </span>
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                最大回撤 {fmtRet(bestStrategy.best.metrics.max_drawdown as number | null | undefined)}
              </span>
              <span className="rounded-md border bg-background px-2 py-1 tabular-nums">
                夏普 {Number(bestStrategy.best.metrics.sharpe ?? 0).toFixed(2)}
              </span>
            </div>
          )}
          <button
            onClick={() => loadForecast(1)}
            disabled={refreshing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-foreground/30 hover:text-foreground disabled:opacity-50"
            title="绕过缓存，用最新可得的行情重新计算走势预测"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            {refreshing ? "重算中" : "用最新数据重算"}
          </button>
          <button
            onClick={() => onRefreshBestStrategy(market, code, true)}
            disabled={bestStrategyLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-foreground/30 hover:text-foreground disabled:opacity-50"
            title={bestStrategy?.best?.strategy?.label
              ? `${isUserSelected ? "当前手动选择" : "当前最稳健"}：${bestStrategy.best.strategy.label}（点击刷新信号）`
              : "运行多时间段测试，刷新稳健策略"}
          >
            {bestStrategyLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TrendingUp className="h-3.5 w-3.5" />}
            {bestStrategyLoading
              ? "策略筛选中"
              : bestStrategy?.reliable === false
                ? "暂无可靠策略"
                : bestStrategy?.best?.strategy?.label
                  ? `${isUserSelected ? "策略" : "最稳健"}：${bestStrategy.best.strategy.label}`
                  : "最稳健策略"}
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
        <ForecastChart data={data} trades={trades.length > 0 ? trades : undefined} />
      ) : null}

      {sortedCandidates.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">策略</span>
          <select
            value={activeStrategy}
            onChange={(e) => pickStrategy(e.target.value)}
            disabled={bestStrategyLoading}
            className="max-w-[16rem] rounded-lg border bg-background px-2 py-1 text-xs disabled:opacity-50"
          >
            {sortedCandidates.map((c) => (
              <option key={c.strategy.name} value={c.strategy.name}>
                {(c.strategy.label || c.strategy.name)}
                {c.strategy.name === robustRecommended ? " · 稳健推荐" : ""}
              </option>
            ))}
          </select>
          {isUserSelected ? (
            <>
              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">手动选择 · 已存为默认</span>
              <button
                onClick={() => pickStrategy(robustRecommended)}
                className="text-[11px] text-primary hover:underline"
              >
                恢复稳健推荐
              </button>
            </>
          ) : (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary">稳健推荐</span>
          )}
          {bestStrategyLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
      )}
      {(bestStrategy || bestStrategyError || bestStrategyLoading) && (
        <div className="mt-3 rounded-lg border bg-muted/25 px-3 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium text-foreground">AI 总结 · {isUserSelected ? "手动选择的策略" : "多时间段最稳健策略"}</p>
              {bestStrategy?.best?.metrics && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {bestStrategy.best.strategy.label || bestStrategy.best.strategy.name}
                  <span className="mx-1">·</span>
                  总收益 {fmtRet(bestStrategy.best.metrics.total_return as number)}（{historyDuration}）
                  <span className="mx-1">·</span>
                  最大亏损 {fmtRet(bestStrategy.best.metrics.max_loss as number | null | undefined)}
                  <span className="mx-1">·</span>
                  最大回撤 {fmtRet(bestStrategy.best.metrics.max_drawdown as number | null | undefined)}
                  <span className="mx-1">·</span>
                  夏普 {Number(bestStrategy.best.metrics.sharpe ?? 0).toFixed(2)}
                </p>
              )}
              {oosMetrics && (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  样本外收益 {fmtRet(oosMetrics.total_return)}
                  <span className="mx-1">·</span>
                  样本外夏普 {Number(oosMetrics.sharpe ?? 0).toFixed(2)}
                  <span className="mx-1">·</span>
                  样本外最大亏损 {fmtRet(oosMetrics.max_loss)}
                  <span className="mx-1">·</span>
                  样本外最大回撤 {fmtRet(oosMetrics.max_drawdown)}
                </p>
              )}
              {bestStrategy?.selection?.confidence_level === "low" && (
                <p className="mt-1 text-[11px] text-amber-600">
                  低可信度 · {bestStrategy.selection.history_note}
                </p>
              )}
            </div>
            <div className="text-right text-[10px] text-muted-foreground">
              {bestStrategy?.selection_cached && <p>年度选择已缓存</p>}
              {bestStrategy?.signal_cached && <p>每日信号已缓存</p>}
              {bestStrategy?.selection?.valid_until && <p>有效至 {bestStrategy.selection.valid_until.slice(0, 10)}</p>}
            </div>
          </div>
          {bestStrategyLoading ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在运行多时间段策略筛选…
            </p>
          ) : bestStrategyError ? (
            <p className="mt-2 text-xs text-red-500">{bestStrategyError}</p>
          ) : bestStrategy?.reliable === false ? (
            <p className="mt-2 text-sm leading-6 text-amber-600">最近一年样本外验证未通过，暂不提供开仓或平仓信号。</p>
          ) : bestStrategy?.summary ? (
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{bestStrategy.summary}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ── rate-limited lazy mount for per-stock charts ─────────────────────────────
// The watchlist can hold 20+ stocks; mounting every ForecastChart (ECharts) at
// once janks the main thread (especially on phones) and makes the page feel
// frozen / navigation unresponsive. A global scheduler mounts at most one chart
// per interval so there is never a burst, regardless of viewport/IO behavior;
// cards scrolled into view jump the queue so they appear promptly.

const MOUNT_INTERVAL_MS = 300;
const _mountQueue: { id: string; run: () => void }[] = [];
let _draining = false;

function _drainMountQueue() {
  if (_draining) return;
  _draining = true;
  const step = () => {
    const job = _mountQueue.shift();
    if (!job) { _draining = false; return; }
    job.run();
    setTimeout(step, MOUNT_INTERVAL_MS);
  };
  step();
}

function scheduleMount(id: string, run: () => void, prioritize = false) {
  const existing = _mountQueue.findIndex((j) => j.id === id);
  if (existing >= 0) {
    if (prioritize) _mountQueue.unshift(..._mountQueue.splice(existing, 1));
    return;
  }
  const job = { id, run };
  if (prioritize) _mountQueue.unshift(job);
  else _mountQueue.push(job);
  _drainMountQueue();
}

function LazyForecastCard(props: {
  market: WatchlistMarket;
  code: string;
  context: number;
  displayHistory: number;
  bestStrategyState?: BestStrategyState;
  onRefreshBestStrategy: (market: WatchlistMarket, code: string, refresh?: boolean, strategy?: string) => void;
}) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const id = `${props.market}-${props.code}`;

  useEffect(() => {
    if (show) return;
    let cancelled = false;
    const mount = () => { if (!cancelled) setShow(true); };
    scheduleMount(id, mount); // queued mount (rate-limited)

    // Scrolled into view → jump the queue so it appears promptly.
    const el = ref.current;
    let io: IntersectionObserver | undefined;
    if (el && typeof IntersectionObserver !== "undefined") {
      io = new IntersectionObserver(
        (entries) => { if (entries.some((e) => e.isIntersecting)) scheduleMount(id, mount, true); },
        { rootMargin: "300px" },
      );
      io.observe(el);
    }
    return () => { cancelled = true; io?.disconnect(); };
  }, [id, show]);

  return (
    <div
      ref={ref}
      id={forecastCardId(props.market, props.code)}
      className="scroll-mt-24"
      style={show ? undefined : { minHeight: 420 }}
    >
      {show ? (
        <ForecastCard {...props} />
      ) : (
        <div className="app-panel animate-pulse" style={{ height: 420 }}>
          <div className="h-4 w-32 rounded bg-muted" />
          <div className="mt-4 h-[320px] rounded-xl bg-muted/40" />
        </div>
      )}
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
  const bestRequestsRef = useRef(new Map<string, Promise<void>>());
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
  const loadBestStrategy = useCallback(async (
    market: WatchlistMarket, code: string, refresh = false, strategyArg?: string,
  ) => {
    const key = stockKey(market, code);
    // explicit arg (incl. "" to restore robust) wins; otherwise use saved default
    const strat = strategyArg !== undefined ? strategyArg : savedStrategyOverride(market, code);
    // strategy-specific session cache so switching doesn't return the wrong run
    const sessionKey = strategySessionKey(market, code) + (strat ? `:${strat}` : "");
    const reqKey = key + (strat ? `:${strat}` : "");
    const cached = refresh
      ? null
      : readSessionCache<HSTechBestStrategyResponse>(sessionKey, STRATEGY_SESSION_TTL);
    if (cached) {
      setBestByKey((prev) => ({
        ...prev,
        [key]: { data: cached, loading: false, error: null },
      }));
      trackProductEvent({ feature: "forecast", action: "result_view", outcome: "success", sessionId: analyticsSessionId("/forecast"), metadata: { route: "/forecast", market, source: "session_cache" } });
      return;
    }
    const pending = bestRequestsRef.current.get(reqKey);
    if (pending) return pending;
    setBestByKey((prev) => ({
      ...prev,
      [key]: { data: prev[key]?.data || null, loading: true, error: null },
    }));
    const started = performance.now();
    const sessionId = analyticsSessionId("/forecast");
    trackProductEvent({ feature: "forecast", action: "task_start", outcome: "unknown", sessionId, metadata: { route: "/forecast", market, source: "best_strategy" } });
    const request = api.getForecastBestPaperStrategy(market, code, refresh, "2020-01-01", strat)
      .then((data) => {
        writeSessionCache(sessionKey, compactStrategyResponse(data));
        setBestByKey((prev) => ({ ...prev, [key]: { data, loading: false, error: null } }));
        trackProductEvent({ feature: "forecast", action: "task_complete", outcome: "success", sessionId, durationMs: performance.now() - started, metadata: { route: "/forecast", market, source: "best_strategy" } });
        trackProductEvent({ feature: "forecast", action: "result_view", outcome: "success", sessionId, metadata: { route: "/forecast", market, source: "best_strategy" } });
      })
      .catch((e) => {
        trackProductEvent({ feature: "forecast", action: "task_complete", outcome: "failure", sessionId, durationMs: performance.now() - started, metadata: { route: "/forecast", market, source: "best_strategy" } });
        setBestByKey((prev) => ({
          ...prev,
          [key]: {
            data: prev[key]?.data || null,
            loading: false,
            error: prev[key]?.data ? null : e?.message || "稳健策略筛选失败",
          },
        }));
      })
      .finally(() => {
        bestRequestsRef.current.delete(reqKey);
      });
    bestRequestsRef.current.set(reqKey, request);
    return request;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadQueue = async () => {
      for (const item of watchlistItems) {
        if (cancelled) break;
        await loadBestStrategy(item.market, item.code, false);
      }
    };
    void loadQueue();
    return () => { cancelled = true; };
  }, [watchlistItems, loadBestStrategy]);

  const recentSignals = useMemo(
    () => recentSignalsFromBestStrategies(watchlistItems, bestByKey, daysAgoISO(7)),
    [watchlistItems, bestByKey],
  );
  const bestLoadingCount = watchlistItems.filter((item) => bestByKey[stockKey(item.market, item.code)]?.loading).length;
  const bestErrorCount = watchlistItems.filter((item) => bestByKey[stockKey(item.market, item.code)]?.error).length;

  return (
    <div className="app-page app-page-compact">
      <div className="app-page-header">
        <div className="app-page-heading">
          <div className="app-page-icon"><LineChart className="h-5 w-5" strokeWidth={1.8} /></div>
          <div>
            <p className="page-kicker">Forecast lab</p>
            <h1 className="app-page-title">走势预测</h1>
            <p className="app-page-description">TimesFM 三个月不确定性锥，同步总览自选股与稳健策略信号。</p>
          </div>
        </div>
        {/* Context length — the same knob drives both forecast and backtest. */}
        <div className="flex items-center gap-2 self-end sm:self-auto">
          <span className="text-xs text-muted-foreground">历史范围</span>
          <div className="app-segmented">
            {CONTEXT_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setContext(o.value)}
                className={cn(
                  "app-segmented-item h-8 px-3",
                  o.value === context
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {total === 0 ? (
        <div className="app-empty-state">
          <LineChart className="h-7 w-7 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">在「总览」页添加A股/港股/美股自选后，此处显示走势预测</p>
        </div>
      ) : (
        <div className="space-y-4">
          <RecentSignalsPanel signals={recentSignals} loadingCount={bestLoadingCount} errorCount={bestErrorCount} />
          <ForecastWatchlistLinks items={watchlistItems} states={bestByKey} />
          {watchlistItems.map((item) => (
            <LazyForecastCard
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
