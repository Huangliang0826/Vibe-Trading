import { useEffect, useState, useCallback, useRef } from "react";
import { LayoutDashboard, RefreshCw, TrendingUp, TrendingDown, Plus, X, Loader2, AlertCircle } from "lucide-react";
import { api, type MarketIndex, type WatchlistQuote, type PriceHistoryPeriod, type PriceHistoryBar, type WatchlistMarket, type ValuationMetric, type ValuationPeriod, type ValuationPoint } from "@/lib/api";
import { PriceHistoryChart } from "@/components/charts/PriceHistoryChart";
import { ValuationChart } from "@/components/charts/ValuationChart";
import { TodayOpportunities } from "@/components/opportunities/TodayOpportunities";
import { cn } from "@/lib/utils";

const REFRESH_MS = 30_000;

// ── helpers ─────────────────────────────────────────────────────────────────

function fmtPrice(price: number, market: string): string {
  if (!price) return "—";
  return market === "us"
    ? price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : price.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function changeColor(pct: number) {
  if (pct > 0) return "text-red-500 dark:text-red-400";
  if (pct < 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-muted-foreground";
}

// localStorage helpers (used as fast cache, backend is source of truth)
function loadList(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}
function saveList(key: string, list: string[]) {
  localStorage.setItem(key, JSON.stringify(list));
}

// ── IndexCard ─────────────────────────────────────────────────────────────

function IndexCard({ idx, flash }: { idx: MarketIndex; flash: boolean }) {
  const color = changeColor(idx.change_pct);
  return (
    <div className={cn(
      "rounded-2xl border bg-card p-4 flex flex-col gap-1 shadow-sm transition-colors duration-700",
      flash && "bg-primary/5 border-primary/20"
    )}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{idx.market}</span>
        {idx.change_pct > 0
          ? <TrendingUp className={cn("h-3.5 w-3.5", color)} />
          : idx.change_pct < 0
          ? <TrendingDown className={cn("h-3.5 w-3.5", color)} />
          : null}
      </div>
      <p className="text-sm font-semibold text-foreground leading-tight">{idx.name}</p>
      <p className={cn("text-2xl font-bold tabular-nums tracking-tight", color)}>
        {fmtPrice(idx.price, idx.market === "美股" ? "us" : "cn")}
      </p>
      <p className={cn("text-sm font-medium tabular-nums", color)}>{fmtPct(idx.change_pct)}</p>
      {idx.prev_close > 0 && (
        <p className="text-[11px] text-muted-foreground tabular-nums mt-0.5">
          昨收&nbsp;{fmtPrice(idx.prev_close, idx.market === "美股" ? "us" : "cn")}
        </p>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-2xl border bg-card p-4 flex flex-col gap-2 animate-pulse">
      <div className="h-3 w-10 bg-muted rounded" />
      <div className="h-4 w-20 bg-muted rounded" />
      <div className="h-7 w-28 bg-muted rounded" />
      <div className="h-4 w-14 bg-muted rounded" />
    </div>
  );
}

// ── Market status ────────────────────────────────────────────────────────

function getMarketStatus(market: "A股" | "港股" | "美股"): { open: boolean; label: string } {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const offsetH = market === "美股" ? -4 : 8; // ET for US, CST for CN/HK
  const local = new Date(utc + offsetH * 3600000);
  const h = local.getHours(), m = local.getMinutes(), t = h * 60 + m;
  const day = local.getDay();
  const weekday = day >= 1 && day <= 5;

  if (market === "A股") {
    const open = weekday && ((t >= 570 && t < 690) || (t >= 780 && t < 900));
    return { open, label: open ? "交易中" : "已收盘" };
  }
  if (market === "港股") {
    const open = weekday && ((t >= 570 && t < 720) || (t >= 780 && t < 960));
    return { open, label: open ? "交易中" : "已收盘" };
  }
  // 美股
  const open = weekday && t >= 570 && t < 960;
  return { open, label: open ? "交易中" : "已收盘" };
}

// ── WatchlistRow ─────────────────────────────────────────────────────────

function scrollToChart(market: WatchlistMarket, code: string) {
  const el = document.getElementById(`chart-${market}-${code.toUpperCase()}`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function WatchlistRow({
  quote,
  market,
  onRemove,
}: {
  quote: WatchlistQuote;
  market: WatchlistMarket;
  onRemove: () => void;
}) {
  const color = changeColor(quote.change_pct);
  const hasData = quote.price > 0;

  return (
    <div className="group flex items-center justify-between px-3 py-2.5 rounded-xl border bg-card hover:bg-muted/30 transition-colors">
      <button
        className="flex flex-col min-w-0 text-left cursor-pointer hover:opacity-70 transition-opacity"
        onClick={() => scrollToChart(market, quote.code)}
      >
        <span className="text-sm font-medium text-foreground leading-tight truncate">
          {quote.name !== quote.code ? quote.name : quote.code}
        </span>
        <span className="text-[11px] text-muted-foreground font-mono">{quote.code}</span>
      </button>

      <div className="flex items-center gap-3 shrink-0">
        {hasData ? (
          <div className="text-right">
            <p className={cn("text-sm font-bold tabular-nums", color)}>
              {fmtPrice(quote.price, market)}
            </p>
            <p className={cn("text-[11px] tabular-nums", color)}>
              {fmtPct(quote.change_pct)}
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <AlertCircle className="h-3 w-3" />
            <span>{quote.error === "not_found" ? "未找到" : "数据获取失败"}</span>
          </div>
        )}
        <button
          onClick={onRemove}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-muted transition-opacity"
          title="移除"
        >
          <X className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </div>
    </div>
  );
}

// ── WatchlistColumn ───────────────────────────────────────────────────────

function WatchlistColumn({
  market,
  label,
  placeholder,
  onCodesChange,
}: {
  market: WatchlistMarket;
  label: string;
  placeholder: string;
  onCodesChange?: (codes: string[]) => void;
}) {
  const storageKey = `watchlist-${market}`;
  const [codes, setCodes] = useState<string[]>(() => loadList(storageKey));
  const [quotes, setQuotes] = useState<Map<string, WatchlistQuote>>(new Map());
  const [adding, setAdding] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Load from backend on mount (backend is source of truth)
  useEffect(() => {
    api.getWatchlistCodes(market).then((res) => {
      if (res.codes.length > 0 || loadList(storageKey).length === 0) {
        setCodes(res.codes);
        saveList(storageKey, res.codes);
      } else {
        // First migration: push localStorage data to backend
        const local = loadList(storageKey);
        if (local.length > 0) {
          api.setWatchlistCodes(market, local).catch(() => {});
        }
      }
    }).catch(() => {
      // Offline fallback: keep localStorage data
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market]);

  // Sync localStorage cache + notify parent
  useEffect(() => {
    saveList(storageKey, codes);
    onCodesChange?.(codes);
  }, [codes, storageKey, onCodesChange]);

  // Auto-focus input when the add form opens
  useEffect(() => {
    if (adding) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [adding]);

  const fetchQuotes = useCallback(async (codeList: string[]) => {
    if (!codeList.length) return;
    try {
      const data = await api.getWatchlistQuote(codeList, market);
      setQuotes((prev) => {
        const next = new Map(prev);
        data.forEach((q) => next.set(q.code.toUpperCase(), q));
        return next;
      });
    } catch {
      // silent — stale quotes stay visible
    }
  }, [market]);

  // Initial load + periodic refresh
  useEffect(() => {
    if (codes.length) fetchQuotes(codes);
    const id = setInterval(() => { if (codes.length) fetchQuotes(codes); }, REFRESH_MS);
    return () => clearInterval(id);
  }, [codes, fetchQuotes]);

  const handleAdd = async () => {
    const code = inputVal.trim().toUpperCase();
    if (!code) return;
    if (codes.map((c) => c.toUpperCase()).includes(code)) {
      setAddError("已在自选列表中");
      return;
    }
    setAddLoading(true);
    setAddError(null);
    try {
      const [result] = await api.getWatchlistQuote([code], market);
      if (!result || result.error === "not_found" || result.price === 0) {
        setAddError("未找到该股票代码");
        return;
      }
      const newCodes = [...codes, code];
      setCodes(newCodes);
      setQuotes((prev) => new Map(prev).set(code, result));
      setInputVal("");
      setAdding(false);
      api.addWatchlistCode(market, code).catch(() => {});
    } catch {
      setAddError("获取行情失败，请检查代码");
    } finally {
      setAddLoading(false);
    }
  };

  const handleRemove = (code: string) => {
    setCodes((prev) => prev.filter((c) => c !== code));
    setQuotes((prev) => { const m = new Map(prev); m.delete(code); return m; });
    api.removeWatchlistCode(market, code).catch(() => {});
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleAdd();
    if (e.key === "Escape") { setAdding(false); setInputVal(""); setAddError(null); }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Column header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">{label}</h2>
        <button
          onClick={() => { setAdding(true); setAddError(null); }}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          添加
        </button>
      </div>

      {/* Inline add form */}
      {adding && (
        <div className="flex flex-col gap-1.5">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              value={inputVal}
              onChange={(e) => { setInputVal(e.target.value); setAddError(null); }}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className="flex-1 px-3 py-2 rounded-xl border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            <button
              onClick={handleAdd}
              disabled={addLoading || !inputVal.trim()}
              className="px-3 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition disabled:opacity-50 flex items-center gap-1"
            >
              {addLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "确认"}
            </button>
            <button
              onClick={() => { setAdding(false); setInputVal(""); setAddError(null); }}
              className="px-3 py-2 rounded-xl border text-sm text-muted-foreground hover:text-foreground transition"
            >
              取消
            </button>
          </div>
          {addError && (
            <p className="text-xs text-red-500 dark:text-red-400 px-1">{addError}</p>
          )}
        </div>
      )}

      {/* Stock list */}
      {codes.length === 0 ? (
        <div className="rounded-2xl border border-dashed bg-card/50 py-10 flex flex-col items-center gap-2 text-center">
          <Plus className="h-6 w-6 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">点击「添加」加入自选</p>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {codes.map((code) => {
            const quote = quotes.get(code.toUpperCase());
            if (!quote) {
              return (
                <div key={code} className="flex items-center justify-between px-3 py-2.5 rounded-xl border bg-card animate-pulse">
                  <div className="h-4 w-24 bg-muted rounded" />
                  <div className="h-4 w-16 bg-muted rounded" />
                </div>
              );
            }
            return (
              <WatchlistRow
                key={code}
                quote={quote}
                market={market}
                onRemove={() => handleRemove(code)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── StockChartCard ────────────────────────────────────────────────────────
// Self-contained chart for a single watchlist stock. A view toggle switches
// between the price chart and valuation series (PE / PB / market cap); each
// view owns its own timeframe selector and data fetch.

type CardView = "price" | ValuationMetric;

const VIEW_TABS: { key: CardView; label: string }[] = [
  { key: "price", label: "价格" },
  { key: "pe", label: "市盈率" },
  { key: "pb", label: "市净率" },
  { key: "mktcap", label: "市值" },
];

function StockChartCard({ code, market, id }: { code: string; market: WatchlistMarket; id?: string }) {
  const [view, setView] = useState<CardView>("price");
  const [name, setName] = useState(code);

  // Price view state
  const [period, setPeriod] = useState<PriceHistoryPeriod>("1Y");
  const [bars, setBars] = useState<PriceHistoryBar[]>([]);
  const [quote, setQuote] = useState<WatchlistQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Valuation view state
  const [valPeriod, setValPeriod] = useState<ValuationPeriod>("5Y");
  const [valPoints, setValPoints] = useState<ValuationPoint[]>([]);
  const [valLoading, setValLoading] = useState(false);

  // Fetch price history (only while the price view is active)
  useEffect(() => {
    if (view !== "price") return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getWatchlistHistory(code, period, market),
      api.getWatchlistQuote([code], market).catch(() => [] as WatchlistQuote[]),
    ])
      .then(([res, quoteList]) => {
        if (cancelled) return;
        setBars(res.bars);
        setQuote(quoteList[0] || null);
        if (res.name) setName(res.name);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "获取走势失败");
        setBars([]);
        setQuote(null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code, period, market, view]);

  // Fetch valuation series (only while a valuation view is active).
  // Clearing stale points + toggling loading happens here (not in onClick) so
  // loading can never get stuck: the same effect that sets it always clears it.
  useEffect(() => {
    if (view === "price") return;
    let cancelled = false;
    setValLoading(true);
    setValPoints([]);
    api.getWatchlistValuation(code, market, view, valPeriod)
      .then((res) => { if (!cancelled) setValPoints(res.points); })
      .catch(() => { if (!cancelled) setValPoints([]); })
      .finally(() => { if (!cancelled) setValLoading(false); });
    return () => { cancelled = true; };
  }, [code, market, view, valPeriod]);

  return (
    <div id={id} className="rounded-2xl border bg-card p-4">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <span className="text-sm font-semibold text-foreground">
          {name && name !== code ? name : ""}
          <span className="font-mono text-xs text-muted-foreground ml-1">{code}</span>
        </span>
        <div className="flex gap-1">
          {VIEW_TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={cn(
                "px-2.5 py-0.5 rounded-md text-xs font-medium transition-colors",
                key === view
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {view === "price" ? (
        <>
          <PriceHistoryChart
            bars={bars}
            period={period}
            onPeriodChange={setPeriod}
            loading={loading}
            height={260}
            showRisk
            quote={quote}
          />
          {error && <p className="text-xs text-red-500 dark:text-red-400 mt-2">{error}</p>}
        </>
      ) : (
        <ValuationChart
          points={valPoints}
          metric={view}
          period={valPeriod}
          onPeriodChange={setValPeriod}
          loading={valLoading}
          height={260}
        />
      )}
    </div>
  );
}

// ── Overview page ─────────────────────────────────────────────────────────

export function Overview() {
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);

  // Watchlist codes (lifted from the columns) drive one chart per stock.
  const [hkCodes, setHkCodes] = useState<string[]>(() => loadList("watchlist-hk"));
  const [usCodes, setUsCodes] = useState<string[]>(() => loadList("watchlist-us"));

  const loadIndices = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    setError(null);
    try {
      const data = await api.getMarketIndices();
      setIndices(data);
      setLastUpdated(new Date());
      setFlash(true);
      setTimeout(() => setFlash(false), 700);
    } catch (e) {
      setError(e instanceof Error ? e.message : "获取指数行情失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadIndices();
    const id = setInterval(() => loadIndices(), REFRESH_MS);
    return () => clearInterval(id);
  }, [loadIndices]);

  const cn_indices = indices.filter((i) => i.market === "A股");
  const hk_indices = indices.filter((i) => i.market === "港股");
  const us_indices = indices.filter((i) => i.market === "美股");

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <LayoutDashboard className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-bold">总览</h1>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-muted-foreground">
              更新于 {lastUpdated.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
          <button
            onClick={() => loadIndices(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-600 dark:text-red-400 border border-red-500/20 bg-red-500/5 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <TodayOpportunities />

      {/* Index cards — A-share */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">A 股指数</h2>
          {!loading && (() => { const s = getMarketStatus("A股"); return (
            <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", s.open ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground")}>{s.label}</span>
          ); })()}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {loading
            ? [0,1,2].map((i) => <SkeletonCard key={i} />)
            : cn_indices.map((idx) => <IndexCard key={idx.code} idx={idx} flash={flash} />)}
        </div>
      </section>

      {/* Index cards — HK */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">港股指数</h2>
          {!loading && (() => { const s = getMarketStatus("港股"); return (
            <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", s.open ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground")}>{s.label}</span>
          ); })()}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {loading
            ? [0,1,2].map((i) => <SkeletonCard key={i} />)
            : hk_indices.map((idx) => <IndexCard key={idx.code} idx={idx} flash={flash} />)}
        </div>
      </section>

      {/* Index cards — US */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">美股指数</h2>
          {!loading && (() => { const s = getMarketStatus("美股"); return (
            <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", s.open ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground")}>{s.label}</span>
          ); })()}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {loading
            ? [0,1,2].map((i) => <SkeletonCard key={i} />)
            : us_indices.map((idx) => <IndexCard key={idx.code} idx={idx} flash={flash} />)}
        </div>
      </section>

      {/* Watchlists */}
      <section className="space-y-2">
        <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">自选</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <WatchlistColumn
            market="hk"
            label="港股自选"
            placeholder="输入港股代码，如 00700"
            onCodesChange={setHkCodes}
          />
          <WatchlistColumn
            market="us"
            label="美股自选"
            placeholder="输入股票代码，如 AAPL"
            onCodesChange={setUsCodes}
          />
        </div>
      </section>

      {/* Price history charts — one per watchlist stock */}
      <section className="space-y-2">
        <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">价格走势</h2>
        {hkCodes.length + usCodes.length > 0 ? (
          <div className="grid grid-cols-1 gap-4">
            {hkCodes.map((code) => (
              <StockChartCard key={`hk-${code}`} id={`chart-hk-${code.toUpperCase()}`} code={code.toUpperCase()} market="hk" />
            ))}
            {usCodes.map((code) => (
              <StockChartCard key={`us-${code}`} id={`chart-us-${code.toUpperCase()}`} code={code.toUpperCase()} market="us" />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed bg-card/50 py-8 flex items-center justify-center">
            <p className="text-sm text-muted-foreground">添加自选股后，此处显示每只股票的走势图</p>
          </div>
        )}
      </section>
    </div>
  );
}
