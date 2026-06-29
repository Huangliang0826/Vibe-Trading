import { useEffect, useState, useRef, useCallback } from "react";
import { Briefcase, Plus, Trash2, Loader2, Play, ChevronDown, ChevronRight } from "lucide-react";
import { ApiError, api, type PaperTradingRun, type PaperHolding, type PaperStrategyConfig, type PaperTrade, type PriceHistoryBar, type PriceHistoryPeriod, type WatchlistMarket, type WatchlistQuote } from "@/lib/api";
import { PaperEquityChart } from "@/components/charts/PaperEquityChart";
import { PaperHoldingPriceChart } from "@/components/charts/PaperHoldingPriceChart";
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

function holdingKey(symbol: string, market: "us" | "hk" | "cn"): string {
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
  | "smart_dca"
  | "trend_volatility_filter"
  | "donchian_breakout"
  | "bollinger_reversion"
  | "trailing_stop"
  | "monthly_rebalance"
  | "macd_divergence"
  | "dual_momentum"
  | "vol_trend_rotation"
  | "atr_trend_stop"
  | "mean_reversion_scaleout"
  | "enhanced_dca_trend"
  | "breakout_pullback"
  | "quality_momentum"
  | "low_volatility_rotation"
  | "volatility_squeeze_breakout"
  | "risk_parity"
  | "price_volume_efficiency";

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
  { value: "trend_volatility_filter", label: "趋势波动过滤", desc: "只在趋势向上时持有，并按波动率降仓" },
  { value: "donchian_breakout", label: "唐奇安突破", desc: "突破长期高点买入，跌破近期低点退出" },
  { value: "bollinger_reversion", label: "布林带反转", desc: "跌破下轨买入，回归均线后卖出" },
  { value: "trailing_stop", label: "移动止损", desc: "趋势确认后买入，用移动止损保护利润" },
  { value: "monthly_rebalance", label: "月度再平衡", desc: "每月把组合调回目标比例" },
  { value: "macd_divergence", label: "MACD 背离", desc: "底背离买入，顶背离或死叉退出" },
  { value: "dual_momentum", label: "双动量轮动", desc: "在组合内只持有动量最强且为正的标的" },
  { value: "vol_trend_rotation", label: "攻守轮动", desc: "趋势向上且波动低时持第一只(股票)，否则换入第二只(债券)" },
  { value: "atr_trend_stop", label: "ATR 趋势止损", desc: "趋势突破后买入，用 ATR 动态止损保护利润" },
  { value: "mean_reversion_scaleout", label: "均值回归分批止盈", desc: "超跌低吸，回归均线先减半，到上轨清仓" },
  { value: "enhanced_dca_trend", label: "趋势增强定投", desc: "按期建仓，弱趋势降仓，趋势回暖再提高投入" },
  { value: "breakout_pullback", label: "突破回踩确认", desc: "先突破前高，再等回踩不破支撑后买入" },
  { value: "quality_momentum", label: "收益质量动量", desc: "追强但惩罚高波动和深回撤，筛选更稳的强势标的" },
  { value: "low_volatility_rotation", label: "低波动防守轮动", desc: "优先持有趋势未破、近期波动最低的标的" },
  { value: "volatility_squeeze_breakout", label: "波动压缩突破", desc: "低波动压缩后向上突破且放量时买入" },
  { value: "risk_parity", label: "组合风险平价", desc: "按近期波动反向分配仓位，让高波动标的少配" },
  { value: "price_volume_efficiency", label: "量价效率轮动", desc: "买上涨高效且放量确认、下跌风险较低的标的" },
];

const STRATEGY_LABELS = Object.fromEntries(
  STRATEGY_OPTIONS.map((option) => [option.value, option.label]),
) as Record<StrategyName, string>;

const OPTIMAL_HISTORY_TITLE_PREFIX = "最优策略候选 -";
const OPTIMAL_HISTORY_RESET_KEY = "paper-trading-optimal-history-reset-v1";

function isOptimalStrategyHistoryRun(run: PaperTradingRun): boolean {
  return (run.title || "").startsWith(OPTIMAL_HISTORY_TITLE_PREFIX) && run.status === "completed";
}

async function loadOptimalHistoryRuns(clearExistingHistory = false): Promise<PaperTradingRun[]> {
  const res = await api.listPaperTradingRuns();
  if (clearExistingHistory) {
    await Promise.all(res.items.map((run) => api.deletePaperTradingRun(run.run_id).catch(() => {})));
    return [];
  }
  return res.items.filter(isOptimalStrategyHistoryRun);
}

const STRATEGY_PRINCIPLES: Record<StrategyName, string> = {
  buy_and_hold: "策略原理：一次性按目标比例买入并长期持有，主要赚取资产本身的长期涨幅。",
  dca: "策略原理：把资金按固定频率分批投入，降低一次性买在高点的风险。",
  grid: "策略原理：在历史价格区间内越跌越买、越涨越卖，主要捕捉震荡行情里的波段收益。",
  momentum_breakout: "策略原理：价格突破近期高点时追随强势趋势，跌破趋势线或触发止损时退出。",
  moving_average_cross: "策略原理：用短期均线和长期均线判断趋势，短线上穿长线时持有，下穿时离场。",
  rsi_reversion: "策略原理：用 RSI 判断超买超卖，超卖时低吸，反弹到偏热区间后卖出。",
  volatility_target: "策略原理：根据近期波动率动态调仓，波动越高仓位越低，优先控制风险暴露。",
  drawdown_rebalance: "策略原理：价格从高点回撤越多越提高仓位，接近前高时降低仓位锁定恢复收益。",
  smart_dca: "策略原理：在普通定投基础上根据均线偏离和波动率调整投入倍率，低估多投、过热少投。",
  trend_volatility_filter: "策略原理：只有价格处于长期上升趋势时才持有，同时用波动率控制仓位大小。",
  donchian_breakout: "策略原理：突破长期高点时买入，跌破近期低点时退出，属于经典趋势跟随方法。",
  bollinger_reversion: "策略原理：价格跌破布林带下轨时认为短期偏离过大，买入等待回归均线后卖出。",
  trailing_stop: "策略原理：趋势确认后买入，随后用移动止损线跟随价格上移，尽量保住已有利润。",
  monthly_rebalance: "策略原理：每月把组合恢复到目标权重，卖出涨多的、补回跌多的，保持风险结构稳定。",
  macd_divergence: "策略原理：当价格创新低但 MACD 抬高（底背离）且柱状图转向时买入，出现顶背离或 MACD 死叉时退出，捕捉动量反转。",
  dual_momentum: "策略原理：每月按近期涨幅给组合内标的排名，只持有动量最强且收益为正的标的（绝对+相对动量），其余转为现金。",
  vol_trend_rotation: "策略原理：以第一只(风险/股票)标的的价格判断行情——站上趋势均线且波动率低于自身一年均值时进攻持股，否则防守换入第二只(债券)标的，靠攻守切换控制回撤。需按“股票在前、债券在后”的顺序添加标的。",
  atr_trend_stop: "策略原理：趋势突破时买入，并用 ATR 波动幅度计算动态止损线；价格继续上涨时止损线随高点上移，趋势破坏或触发止损时离场。",
  mean_reversion_scaleout: "策略原理：价格跌到统计下轨时认为短期超跌并买入，回到均线附近先减半，到上轨或触发止损时退出，用分批止盈降低反转失败风险。",
  enhanced_dca_trend: "策略原理：保留定投的分批建仓纪律，但长期趋势偏弱时降低目标仓位，趋势向上且价格仍偏低时提高投入，避免在弱势里机械满仓。",
  breakout_pullback: "策略原理：不在突破当天追高，而是先确认价格突破前高，再等待回踩突破位附近且不破短期支撑后买入，减少假突破带来的追高风险。",
  quality_momentum: "策略原理：每月按收益质量排序，既看过去涨幅，也扣除波动率和最大回撤惩罚，只持有表现强且回撤质量更好的标的。",
  low_volatility_rotation: "策略原理：每月在趋势未破的标的里选择近期波动最低者，目标不是追求最强涨幅，而是优先降低组合波动和下行风险。",
  volatility_squeeze_breakout: "策略原理：先等待布林带宽度/波动率降到历史低分位，随后只有价格向上突破且成交量确认时买入，捕捉压缩后的趋势释放。",
  risk_parity: "策略原理：按近期波动率反向分配组合权重，波动大的标的少配，波动小的标的多配，让组合风险贡献更均衡。",
  price_volume_efficiency: "策略原理：把价格行为切成上涨效率和下跌效率，再看成交量是否配合；上涨高效且放量确认加分，下跌高效且放量确认扣分，最后按综合 rank 轮动持有前几名。",
};

function strategyParamsFor(name: StrategyName, dcaFrequency: string, gridCount: number): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (name === "dca" || name === "smart_dca" || name === "enhanced_dca_trend") params.frequency = dcaFrequency;
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
  return finiteNumber(bm.max_loss, -Infinity) - finiteNumber(am.max_loss, -Infinity);
}

function buildLatestTradeSummary(run: PaperTradingRun): string {
  const trades = run.trades ?? [];
  if (!trades.length) return "最新交易：暂无交易记录，当前没有可跟随的买卖动作。";

  const events = trades.flatMap((trade) => {
    const entryAction = trade.direction >= 0 ? "买入" : "卖出";
    const exitAction = trade.direction >= 0 ? "卖出" : "买入平空";
    return [
      {
        date: trade.entry_time,
        action: entryAction,
        symbol: trade.symbol,
        price: trade.entry_price,
        isEndClose: false,
      },
      {
        date: trade.exit_time,
        action: exitAction,
        symbol: trade.symbol,
        price: trade.exit_price,
        isEndClose: trade.exit_reason === "end_of_backtest",
      },
    ];
  }).sort((a, b) => b.date.localeCompare(a.date));

  const latestActionable = events.find((event) => !event.isEndClose);
  if (latestActionable) {
    return `最新交易：${latestActionable.date} ${latestActionable.action} ${latestActionable.symbol}，价格 ${latestActionable.price.toFixed(2)}。`;
  }

  const latestEntry = events.find((event) => event.action === "买入" || event.action === "卖出");
  if (latestEntry) {
    return `最新交易：最近一次实际动作是 ${latestEntry.date} ${latestEntry.action} ${latestEntry.symbol}，价格 ${latestEntry.price.toFixed(2)}；之后没有新的主动信号，当前更接近继续持有或等待下一次信号。`;
  }

  return "最新交易：只有回测结束统计平仓记录，不代表策略主动发出买卖信号。";
}

function buildOptimalSummary(runs: PaperTradingRun[], bestRunId: string | null): string {
  if (!bestRunId) return "";
  const completed = runs.filter((run) => run.status === "completed" && run.metrics);
  const best = completed.find((run) => run.run_id === bestRunId);
  if (!best?.metrics) return "";

  const sorted = [...completed].sort(compareRuns);
  const second = sorted.find((run) => run.run_id !== bestRunId);
  const bestName = STRATEGY_LABELS[best.strategy.name as StrategyName] || best.strategy.name;
  const principle = STRATEGY_PRINCIPLES[best.strategy.name as StrategyName];
  const bestSharpe = finiteNumber(best.metrics.sharpe);
  const bestReturn = finiteNumber(best.metrics.total_return);
  const bestDrawdown = finiteNumber(best.metrics.max_loss);
  const bestTrades = finiteNumber(best.metrics.trade_count, best.trades?.length ?? 0);

  const reasons: string[] = [
    principle,
    `${bestName} 在当前组合和日期区间里综合排名第一，主要因为它的夏普比率为 ${bestSharpe.toFixed(2)}，在“风险调整后收益”排序中最占优。`,
  ];

  if (second?.metrics) {
    const secondName = STRATEGY_LABELS[second.strategy.name as StrategyName] || second.strategy.name;
    const secondSharpe = finiteNumber(second.metrics.sharpe);
    const secondReturn = finiteNumber(second.metrics.total_return);
    const secondDrawdown = finiteNumber(second.metrics.max_loss);
    reasons.push(
      `相比第二名 ${secondName}，它的夏普差距为 ${(bestSharpe - secondSharpe).toFixed(2)}，总收益差距为 ${fmtPctValue((bestReturn - secondReturn) * 100)}，最大亏损差距为 ${fmtPctValue((bestDrawdown - secondDrawdown) * 100)}。`,
    );
  }

  const drawdownText = bestDrawdown < -0.2 ? "相对本金的最大亏损仍然偏高，适合作为候选而不是直接实盘规则。" : "相对本金的最大亏损可控，说明它没有单纯靠放大风险取胜。";
  const tradeText = bestTrades <= 2 ? "交易次数很少，结果更接近中长期持有表现。" : `交易次数为 ${bestTrades.toFixed(0)} 次，说明它通过更主动的调仓改善了表现。`;
  reasons.push(`本次回测总收益为 ${fmtPctValue(bestReturn * 100)}，最大亏损为 ${fmtPctValue(bestDrawdown * 100)}；${drawdownText}${tradeText}`);
  reasons.push(buildLatestTradeSummary(best));

  return reasons.join(" ");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function todayInputValue(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isMissingRunError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function WatchlistQuickAdd({
  title,
  market,
  quotes,
  holdings,
  onAdd,
}: {
  title: string;
  market: "hk" | "us" | "cn";
  quotes: WatchlistQuote[];
  holdings: PaperHolding[];
  onAdd: (quote: WatchlistQuote, market: "hk" | "us" | "cn") => void;
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
  const [newMarket, setNewMarket] = useState<"us" | "hk" | "cn">("hk");
  const [quickQuotes, setQuickQuotes] = useState<{ hk: WatchlistQuote[]; us: WatchlistQuote[]; cn: WatchlistQuote[] }>({ hk: [], us: [], cn: [] });
  const [quickLoading, setQuickLoading] = useState(false);

  // ── Strategy state ──
  const [strategy, setStrategy] = useState<StrategyName>("buy_and_hold");
  const [dcaFrequency, setDcaFrequency] = useState("monthly");
  const [gridCount, setGridCount] = useState(5);

  // ── Config state ──
  const [startDate, setStartDate] = useState("2020-01-01");
  const [endDate, setEndDate] = useState(() => todayInputValue());
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
  const [singlePricePeriod, setSinglePricePeriod] = useState<PriceHistoryPeriod>("ALL");
  const [singlePriceBars, setSinglePriceBars] = useState<PriceHistoryBar[]>([]);
  const [singlePriceLoading, setSinglePriceLoading] = useState(false);
  const [singlePriceError, setSinglePriceError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load history on mount ──
  useEffect(() => {
    const shouldClearExistingHistory = localStorage.getItem(OPTIMAL_HISTORY_RESET_KEY) !== "done";
    loadOptimalHistoryRuns(shouldClearExistingHistory)
      .then((items) => {
        setRuns(items);
        if (shouldClearExistingHistory) localStorage.setItem(OPTIMAL_HISTORY_RESET_KEY, "done");
      })
      .catch(() => {});
  }, []);

  const refreshRuns = useCallback(() => {
    loadOptimalHistoryRuns()
      .then(setRuns)
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadQuickQuotes = async () => {
      setQuickLoading(true);
      try {
        const [hkCodesRes, usCodesRes, cnCodesRes] = await Promise.all([
          api.getWatchlistCodes("hk").catch(() => ({ codes: loadWatchlistCodes("hk") })),
          api.getWatchlistCodes("us").catch(() => ({ codes: loadWatchlistCodes("us") })),
          api.getWatchlistCodes("cn").catch(() => ({ codes: loadWatchlistCodes("cn") })),
        ]);
        const hkCodes = hkCodesRes.codes.length ? hkCodesRes.codes : loadWatchlistCodes("hk");
        const usCodes = usCodesRes.codes.length ? usCodesRes.codes : loadWatchlistCodes("us");
        const cnCodes = cnCodesRes.codes.length ? cnCodesRes.codes : loadWatchlistCodes("cn");
        const [hkQuotes, usQuotes, cnQuotes] = await Promise.all([
          hkCodes.length ? api.getWatchlistQuote(hkCodes, "hk").catch(() => [] as WatchlistQuote[]) : Promise.resolve([]),
          usCodes.length ? api.getWatchlistQuote(usCodes, "us").catch(() => [] as WatchlistQuote[]) : Promise.resolve([]),
          cnCodes.length ? api.getWatchlistQuote(cnCodes, "cn").catch(() => [] as WatchlistQuote[]) : Promise.resolve([]),
        ]);
        if (!cancelled) setQuickQuotes({ hk: hkQuotes, us: usQuotes, cn: cnQuotes });
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
          refreshRuns();
        }
      } catch (e) {
        if (isMissingRunError(e)) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setActiveRun(null);
          setError("这条回测记录已不存在，已刷新历史列表。");
          refreshRuns();
        }
      }
    }, 1500);
  }, [refreshRuns]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const singleHolding = activeRun?.status === "completed"
    ? activeRun.holdings.filter((holding) => holding.symbol.toUpperCase() !== "CASH")[0]
    : null;
  const hasSingleHolding = activeRun?.status === "completed"
    && activeRun.holdings.filter((holding) => holding.symbol.toUpperCase() !== "CASH").length === 1
    && !!singleHolding;

  useEffect(() => {
    if (!hasSingleHolding || !singleHolding) {
      setSinglePriceBars([]);
      setSinglePriceError(null);
      return;
    }

    let cancelled = false;
    setSinglePriceLoading(true);
    setSinglePriceError(null);
    api.getWatchlistHistory(singleHolding.symbol, singlePricePeriod, singleHolding.market)
      .then((res) => {
        if (cancelled) return;
        setSinglePriceBars(res.bars);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setSinglePriceBars([]);
        setSinglePriceError(e instanceof Error ? e.message : "获取标的价格走势失败");
      })
      .finally(() => {
        if (!cancelled) setSinglePriceLoading(false);
      });
    return () => { cancelled = true; };
  }, [hasSingleHolding, singleHolding?.market, singleHolding?.symbol, singlePricePeriod]);

  // ── Add holding ──
  const addHoldingToPortfolio = (symbol: string, market: "us" | "hk" | "cn", name?: string) => {
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

  const addQuickQuote = (quote: WatchlistQuote, market: "hk" | "us" | "cn") => {
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
        const latest = await Promise.all(runIds.map(async (runId) => {
          try {
            return await api.getPaperTradingRun(runId);
          } catch (e) {
            if (isMissingRunError(e)) return null;
            throw e;
          }
        }));
        const available = latest.filter((run): run is PaperTradingRun => run !== null);
        const availableIds = new Set(available.map((run) => run.run_id));
        runIds.forEach((runId) => {
          if (!availableIds.has(runId)) latestById.delete(runId);
        });
        available.forEach((run) => latestById.set(run.run_id, run));
        const missing = latest.length - available.length;
        const finished = available.filter((run) => run.status === "completed" || run.status === "failed").length + missing;
        setOptimalRuns(available);
        setOptimalProgress(`最优策略回测中：${finished}/${latest.length} 已完成${missing ? `，${missing} 条记录已不存在` : ""}`);
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
      await Promise.all(
        finalRuns
          .filter((run) => run.run_id !== best.run_id)
          .map((run) => api.deletePaperTradingRun(run.run_id).catch(() => {})),
      );
      setOptimalRuns(finalRuns);
      setOptimalBestRunId(best.run_id);
      setActiveRun(best);
      setStrategy(best.strategy.name as StrategyName);
      setOptimalProgress(`最优策略：${STRATEGY_LABELS[best.strategy.name as StrategyName] || best.strategy.name}`);
      refreshRuns();
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
    } catch (e) {
      if (isMissingRunError(e)) {
        setActiveRun(null);
        setError("这条回测记录已不存在，已刷新历史列表。");
        refreshRuns();
      }
    }
  };

  const deleteRun = async (runId: string) => {
    try {
      await api.deletePaperTradingRun(runId);
      setRuns((prev) => prev.filter((r) => r.run_id !== runId));
      if (activeRun?.run_id === runId) setActiveRun(null);
    } catch { /* ignore */ }
  };

  const m = activeRun?.metrics;
  const optimalSummary = buildOptimalSummary(optimalRuns, optimalBestRunId);

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
          <WatchlistQuickAdd
            title="A股自选"
            market="cn"
            quotes={quickQuotes.cn}
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
            onChange={(e) => setNewMarket(e.target.value as "us" | "hk" | "cn")}
            className="rounded-lg border bg-background px-2 py-1.5 text-sm"
          >
            <option value="us">美股</option>
            <option value="hk">港股</option>
            <option value="cn">A股</option>
          </select>
          <input
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void addHolding();
            }}
            placeholder={newMarket === "us" ? "输入代码 如 AAPL" : newMarket === "cn" ? "输入代码 如 600519" : "输入代码 如 0700"}
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
                    <td className="px-3 py-2">{h.symbol === "CASH" ? "—" : h.market === "us" ? "美股" : h.market === "cn" ? "A股" : "港股"}</td>
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
          {optimalSummary && (
            <div className="mb-3 rounded-lg border bg-muted/30 px-3 py-2.5">
              <p className="text-xs font-medium text-foreground">AI 总结</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {optimalSummary}
              </p>
            </div>
          )}
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
                        {run.status === "completed" ? pct(metrics.max_loss as number) : "—"}
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
                  value={pct(m.max_loss as number)}
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
                  <PaperEquityChart
                    data={activeRun.equity_curve}
                    initialCapital={activeRun.initial_total_usd}
                    trades={activeRun.trades}
                    height={300}
                  />
                </div>
              )}

              {hasSingleHolding && singleHolding && (
                <div className="rounded-xl border bg-card p-4">
                  <div className="mb-3">
                    <h3 className="text-sm font-semibold">标的价格走势</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {holdingNames[holdingKey(singleHolding.symbol, singleHolding.market)] || singleHolding.symbol}
                      <span className="ml-1 font-mono">{singleHolding.symbol}</span>
                    </p>
                  </div>
                  <PaperHoldingPriceChart
                    bars={singlePriceBars}
                    trades={activeRun.trades}
                    period={singlePricePeriod}
                    onPeriodChange={setSinglePricePeriod}
                    loading={singlePriceLoading}
                    height={320}
                  />
                  {singlePriceError && <p className="mt-2 text-xs text-red-500">{singlePriceError}</p>}
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
