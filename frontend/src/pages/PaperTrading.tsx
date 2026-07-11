import { useEffect, useState, useRef, useCallback } from "react";
import { Briefcase, Plus, Trash2, Loader2, Play, ChevronDown, ChevronRight } from "lucide-react";
import { ApiError, api, type PaperTradingRun, type PaperHolding, type PaperStrategyConfig, type PaperTrade, type PriceHistoryBar, type PriceHistoryPeriod, type WatchlistMarket, type WatchlistQuote, type RobustOptimizeResult } from "@/lib/api";
import { PaperEquityChart } from "@/components/charts/PaperEquityChart";
import { PaperHoldingPriceChart } from "@/components/charts/PaperHoldingPriceChart";
import { cn } from "@/lib/utils";
import { buildRobustWinnerRunRequest } from "@/lib/paper-trading-robust";

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
  | "dca_then_hold"
  | "dca_two_year_then_hold"
  | "trend_volatility_filter"
  | "donchian_breakout"
  | "bollinger_reversion"
  | "trailing_stop"
  | "monthly_rebalance"
  | "macd_divergence"
  | "dual_momentum"
  | "atr_trend_stop"
  | "mean_reversion_scaleout"
  | "enhanced_dca_trend"
  | "breakout_pullback"
  | "quality_momentum"
  | "low_volatility_rotation"
  | "volatility_squeeze_breakout"
  | "risk_parity"
  | "price_volume_efficiency"
  | "accelerated_dca_entry"
  | "deep_drawdown_recovery"
  | "ma200_timing"
  | "value_averaging";

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
  { value: "dca_then_hold", label: "三年定投后持有", desc: "把现金分三年逐月投入，投完长期持有" },
  { value: "dca_two_year_then_hold", label: "两年定投后持有", desc: "把现金分两年逐月投入，投完长期持有" },
  { value: "accelerated_dca_entry", label: "回撤加速建仓", desc: "首投25%，十二个月分批；跌10%投20%，跌20%投完" },
  { value: "deep_drawdown_recovery", label: "深跌分批止盈", desc: "距三年高点跌40%分十次建仓，涨至平均成本140%后分五次卖出" },
  { value: "trend_volatility_filter", label: "趋势波动过滤", desc: "只在趋势向上时持有，并按波动率降仓" },
  { value: "donchian_breakout", label: "唐奇安突破", desc: "突破长期高点买入，跌破近期低点退出" },
  { value: "bollinger_reversion", label: "布林带反转", desc: "跌破下轨买入，回归均线后卖出" },
  { value: "trailing_stop", label: "移动止损", desc: "趋势确认后买入，用移动止损保护利润" },
  { value: "monthly_rebalance", label: "月度再平衡", desc: "每月把组合调回目标比例" },
  { value: "macd_divergence", label: "MACD 背离", desc: "底背离买入，顶背离或死叉退出" },
  { value: "dual_momentum", label: "双动量轮动", desc: "在组合内只持有动量最强且为正的标的" },
  { value: "atr_trend_stop", label: "ATR 趋势止损", desc: "趋势突破后买入，用 ATR 动态止损保护利润" },
  { value: "mean_reversion_scaleout", label: "均值回归分批止盈", desc: "超跌低吸，回归均线先减半，到上轨清仓" },
  { value: "enhanced_dca_trend", label: "趋势增强定投", desc: "按期建仓，弱趋势降仓，趋势回暖再提高投入" },
  { value: "breakout_pullback", label: "突破回踩确认", desc: "先突破前高，再等回踩不破支撑后买入" },
  { value: "quality_momentum", label: "收益质量动量", desc: "追强但惩罚高波动和深回撤，筛选更稳的强势标的" },
  { value: "low_volatility_rotation", label: "低波动防守轮动", desc: "优先持有趋势未破、近期波动最低的标的" },
  { value: "volatility_squeeze_breakout", label: "波动压缩突破", desc: "低波动压缩后向上突破且放量时买入" },
  { value: "risk_parity", label: "组合风险平价", desc: "按近期波动反向分配仓位，让高波动标的少配" },
  { value: "price_volume_efficiency", label: "量价效率轮动", desc: "买上涨高效且放量确认、下跌风险较低的标的" },
  { value: "ma200_timing", label: "200日均线择时", desc: "站上200日均线满仓，跌破清仓持币，避开深度熊市" },
  { value: "value_averaging", label: "价值平均定投", desc: "市值沿目标路径逐月增长，跌多补、涨多卖，低买高卖" },
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
  dca_then_hold: "策略原理：把全部资金平均分成三年、按所选频率（默认每月）逐步投入选定标的，三年内分批建仓摊低成本；投完后不再买卖，长期持有赚取标的长期涨幅。回测区间建议不少于三年，否则资金无法在区间内投完。",
  dca_two_year_then_hold: "策略原理：把全部资金平均分成两年、按所选频率（默认每月）逐步投入选定标的；两年建仓完成后不再买卖，长期持有赚取标的长期涨幅。",
  trend_volatility_filter: "策略原理：只有价格处于长期上升趋势时才持有，同时用波动率控制仓位大小。",
  donchian_breakout: "策略原理：突破长期高点时买入，跌破近期低点时退出，属于经典趋势跟随方法。",
  bollinger_reversion: "策略原理：价格跌破布林带下轨时认为短期偏离过大，买入等待回归均线后卖出。",
  trailing_stop: "策略原理：趋势确认后买入，随后用移动止损线跟随价格上移，尽量保住已有利润。",
  monthly_rebalance: "策略原理：每月把组合恢复到目标权重，卖出涨多的、补回跌多的，保持风险结构稳定。",
  macd_divergence: "策略原理：当价格创新低但 MACD 抬高（底背离）且柱状图转向时买入，出现顶背离或 MACD 死叉时退出，捕捉动量反转。",
  dual_momentum: "策略原理：每月按近期涨幅给组合内标的排名，只持有动量最强且收益为正的标的（绝对+相对动量），其余转为现金。",
  atr_trend_stop: "策略原理：趋势突破时买入，并用 ATR 波动幅度计算动态止损线；价格继续上涨时止损线随高点上移，趋势破坏或触发止损时离场。",
  mean_reversion_scaleout: "策略原理：价格跌到统计下轨时认为短期超跌并买入，回到均线附近先减半，到上轨或触发止损时退出，用分批止盈降低反转失败风险。",
  enhanced_dca_trend: "策略原理：保留定投的分批建仓纪律，但长期趋势偏弱时降低目标仓位，趋势向上且价格仍偏低时提高投入，避免在弱势里机械满仓。",
  breakout_pullback: "策略原理：不在突破当天追高，而是先确认价格突破前高，再等待回踩突破位附近且不破短期支撑后买入，减少假突破带来的追高风险。",
  quality_momentum: "策略原理：每月按收益质量排序，既看过去涨幅，也扣除波动率和最大回撤惩罚，只持有表现强且回撤质量更好的标的。",
  low_volatility_rotation: "策略原理：每月在趋势未破的标的里选择近期波动最低者，目标不是追求最强涨幅，而是优先降低组合波动和下行风险。",
  volatility_squeeze_breakout: "策略原理：先等待布林带宽度/波动率降到历史低分位，随后只有价格向上突破且成交量确认时买入，捕捉压缩后的趋势释放。",
  risk_parity: "策略原理：按近期波动率反向分配组合权重，波动大的标的少配，波动小的标的多配，让组合风险贡献更均衡。",
  price_volume_efficiency: "策略原理：把价格行为切成上涨效率和下跌效率，再看成交量是否配合；上涨高效且放量确认加分，下跌高效且放量确认扣分，最后按综合 rank 轮动持有前几名。",
  accelerated_dca_entry: "策略原理：T0先投入目标预算的25%，剩余75%在之后十二个月的首个交易日按固定基础金额投入；相对T0收盘回撤达到10%时当期投入总预算的20%，达到20%时一次性投入全部剩余资金。",
  deep_drawdown_recovery: "策略原理：价格相对此前三年的最高收盘价下跌40%后开始建仓，将资金分十份、每隔一个月投入一份；收盘价达到加权平均成本的140%后锁定退出计划，从下一交易日开始分五份、每隔一个月卖出一份。触发退出后即使价格回落也继续执行。",
  ma200_timing: "策略原理：收盘价站上200日均线时满仓持有，跌破则清仓持币等待，用最简单的长期趋势过滤避开深度熊市；代价是震荡市里可能被反复打止损。",
  value_averaging: "策略原理：让持仓市值沿预定路径逐月增长——低于路径就补足缺口（跌得越多买得越多），高于路径就卖出盈余落袋，比普通定投更贴近低买高卖。",
};

function strategyParamsFor(name: StrategyName, dcaFrequency: string, gridCount: number): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (name === "dca" || name === "smart_dca" || name === "enhanced_dca_trend" || name === "dca_then_hold" || name === "dca_two_year_then_hold") params.frequency = dcaFrequency;
  if (name === "grid") params.grid_count = gridCount;
  if (name === "accelerated_dca_entry") {
    params.initial_pct = 0.25;
    params.n_months = 12;
    params.accelerate_drawdown = 0.1;
    params.all_in_drawdown = 0.2;
    params.accelerated_investment_pct = 0.2;
  }
  if (name === "deep_drawdown_recovery") {
    params.drawdown_threshold = 0.4;
    params.take_profit_pct = 0.4;
    params.tranches = 10;
    params.exit_tranches = 5;
    params.lookback_years = 3;
  }
  return params;
}

// Balance score: reward total return, penalise the worst loss-from-principal
// at 2× weight. Higher is better. This is the primary "最优策略" criterion —
// it favours strategies that pair strong returns with a controlled max loss.
const MAX_LOSS_PENALTY = 2;

function balanceScore(metrics: Record<string, unknown>): number {
  const ret = finiteNumber(metrics.total_return, -Infinity);
  if (!Number.isFinite(ret)) return -Infinity;
  const loss = Math.abs(finiteNumber(metrics.max_loss, 0));
  return ret - MAX_LOSS_PENALTY * loss;
}

function compareRuns(a: PaperTradingRun, b: PaperTradingRun): number {
  const am = a.metrics ?? {};
  const bm = b.metrics ?? {};
  const scoreDiff = balanceScore(bm) - balanceScore(am);
  if (Math.abs(scoreDiff) > 1e-9) return scoreDiff;
  // Tiebreakers: higher total return, then smaller loss.
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
  const bestReturn = finiteNumber(best.metrics.total_return);
  const bestDrawdown = finiteNumber(best.metrics.max_loss);
  const bestScore = balanceScore(best.metrics);
  const bestTrades = finiteNumber(best.metrics.trade_count, best.trades?.length ?? 0);

  const reasons: string[] = [
    principle,
    `${bestName} 在当前组合和日期区间里综合排名第一，平衡得分（总收益 ${fmtPctValue(bestReturn * 100)} − 2×最大亏损 ${fmtPctValue(Math.abs(bestDrawdown) * 100)}）为 ${fmtPctValue(bestScore * 100)}，在“收益与亏损平衡”排序中最高。`,
  ];

  if (second?.metrics) {
    const secondName = STRATEGY_LABELS[second.strategy.name as StrategyName] || second.strategy.name;
    const secondScore = balanceScore(second.metrics);
    const secondReturn = finiteNumber(second.metrics.total_return);
    const secondDrawdown = finiteNumber(second.metrics.max_loss);
    reasons.push(
      `相比第二名 ${secondName}，它的平衡得分高 ${fmtPctValue((bestScore - secondScore) * 100)}，总收益差距为 ${fmtPctValue((bestReturn - secondReturn) * 100)}，最大亏损差距为 ${fmtPctValue((bestDrawdown - secondDrawdown) * 100)}。`,
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

  // ── Run state ──
  const [runs, setRuns] = useState<PaperTradingRun[]>([]);
  const [activeRun, setActiveRun] = useState<PaperTradingRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [optimalProgress, setOptimalProgress] = useState("");
  const [optimalRuns, setOptimalRuns] = useState<PaperTradingRun[]>([]);
  const [optimalBestRunId, setOptimalBestRunId] = useState<string | null>(null);
  const [robustResult, setRobustResult] = useState<RobustOptimizeResult | null>(null);
  const [robustLoading, setRobustLoading] = useState(false);
  const [robustAutoRunning, setRobustAutoRunning] = useState(false);
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
      // 每个市场独立请求、各自返回各自上屏:港股/A股不用陪美股慢源等待
      const loadMarket = async (market: "hk" | "us" | "cn") => {
        const codesRes = await api.getWatchlistCodes(market)
          .catch(() => ({ codes: loadWatchlistCodes(market) }));
        const codes = codesRes.codes.length ? codesRes.codes : loadWatchlistCodes(market);
        const quotes = codes.length
          ? await api.getWatchlistQuote(codes, market).catch(() => [] as WatchlistQuote[])
          : [];
        if (!cancelled) setQuickQuotes((prev) => ({ ...prev, [market]: quotes }));
      };
      try {
        await Promise.all([loadMarket("hk"), loadMarket("us"), loadMarket("cn")]);
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
  const pollRun = useCallback((runId: string, onFinished?: () => void) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const run = await api.getPaperTradingRun(runId);
        setActiveRun(run);
        if (run.status === "completed" || run.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          refreshRuns();
          onFinished?.();
        }
      } catch (e) {
        if (isMissingRunError(e)) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setActiveRun(null);
          setError("这条回测记录已不存在，已刷新历史列表。");
          refreshRuns();
          onFinished?.();
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
        initial_hkd: 0,
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
          initial_hkd: 0,
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

  // ── Multi-period (robust) strategy test ──
  const handleRobustOptimize = async () => {
    if (holdings.length === 0 || !allocValid) return;
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setRobustLoading(true);
    setError(null);
    setActiveRun(null);
    setOptimalRuns([]);
    setRobustResult(null);
    try {
      const result = await api.robustOptimizePaperTrading({
        holdings,
        strategies: STRATEGY_OPTIONS.map((option) => ({
          name: option.value,
          params: strategyParamsFor(option.value, dcaFrequency, gridCount),
        })),
        end_date: endDate,
        initial_usd: initialUsd,
        initial_hkd: 0,
        window_years: 3,
        step_years: 1,
      });
      setRobustResult(result);
      if (!result.best_strategy) throw new Error("多时间段测试没有找到可用的最稳健策略");
      const winner = result.best_strategy as StrategyName;
      setStrategy(winner);
      const run = await api.createPaperTradingRun(buildRobustWinnerRunRequest({
        bestStrategy: winner,
        winnerParams: strategyParamsFor(winner, dcaFrequency, gridCount),
        holdings,
        startDate,
        endDate,
        initialUsd,
        initialHkd: 0,
      }));
      setActiveRun(run);
      setRobustAutoRunning(true);
      pollRun(run.run_id, () => setRobustAutoRunning(false));
    } catch (e: any) {
      setError(e?.message || "多时间段测试失败");
    } finally {
      setRobustLoading(false);
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
          {(strategy === "dca" || strategy === "smart_dca" || strategy === "dca_then_hold" || strategy === "dca_two_year_then_hold") && (
            <div className="flex items-center gap-3 pl-1">
              <label className="text-xs text-muted-foreground">
                {strategy === "smart_dca" ? "智能定投频率" : strategy === "dca_then_hold" ? "三年定投频率" : strategy === "dca_two_year_then_hold" ? "两年定投频率" : "定投频率"}
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
        </div>

        <div className="flex items-center justify-end">
          <div className="flex items-center gap-2">
            <button
              onClick={handleOptimizeStrategies}
              disabled={submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
                submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid
                  ? "cursor-not-allowed bg-muted text-muted-foreground"
                  : "bg-background hover:bg-accent",
              )}
            >
              {optimizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              最优策略
            </button>
            <button
              onClick={handleRobustOptimize}
              disabled={submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid}
              title="在多个滚动时间段上分别测试，取平均排名最稳健的策略"
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
                submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid
                  ? "cursor-not-allowed bg-muted text-muted-foreground"
                  : "bg-background hover:bg-accent",
              )}
            >
              {robustLoading || robustAutoRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {robustAutoRunning ? "运行赢家回测" : "多时间段测试"}
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                submitting || optimizing || robustLoading || robustAutoRunning || holdings.length === 0 || !allocValid
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
        {robustLoading && <p className="text-xs text-muted-foreground">多时间段测试运行中…（在多个窗口上回测全部策略，请稍候）</p>}
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>

      {optimalRuns.length > 0 && (
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">最优策略对比</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                排序规则：平衡得分优先（总收益 − 2×最大亏损），打平再看总收益、最大亏损
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

      {robustResult && (
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-2">
            <h2 className="text-sm font-semibold">多时间段稳健性测试</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              在 {robustResult.windows.filter((w) => !w.is_full).length} 个 {robustResult.window_years} 年窗口（每 {robustResult.step_years} 年滚动）+ 全历史上分别按平衡得分排名，取
              <span className="font-medium text-foreground">平均排名</span>最优。共同数据区间 {robustResult.data_start} ~ {robustResult.data_end}
              （最多 {robustResult.history_cap_years} 年）
              {robustResult.limiting_symbols.length > 0 && `，受 ${robustResult.limiting_symbols.join("、")} 的历史长度限制`}。
              这是稳健性筛选，降低对单一时段的过拟合，但仍基于历史、不代表未来。
            </p>
          </div>
          {robustResult.best_strategy && (
            <div className="mb-3 rounded-lg border bg-primary/10 px-3 py-2 text-sm">
              最稳健策略：<span className="font-semibold">{STRATEGY_LABELS[robustResult.best_strategy as StrategyName] || robustResult.best_strategy}</span>
              {(() => {
                const b = robustResult.strategies.find((s) => s.name === robustResult.best_strategy);
                return b ? <span className="ml-2 text-xs text-muted-foreground">平均排名 {b.mean_rank}（最差 {b.worst_rank} · 波动 {b.rank_std}）</span> : null;
              })()}
            </div>
          )}
          {(robustResult.baseline || robustResult.ensemble || (robustResult.param_sensitivity?.length ?? 0) > 0) && (
            <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {robustResult.baseline && (() => {
                const winner = robustResult.strategies.find((s) => s.name === robustResult.best_strategy);
                const beat = winner?.windows_beating_hold;
                const excess = winner?.mean_excess_vs_hold;
                const winnerBeatsHold = beat != null && beat.beating > beat.total / 2;
                return (
                  <div className="rounded-lg border px-3 py-2 text-xs leading-5">
                    <span className="font-medium">对照基准 · 买入持有</span>
                    <span className="ml-2 text-muted-foreground">平均收益 <span className="font-semibold tabular-nums text-foreground">{pct(robustResult.baseline.mean_return)}</span> · 平均排名 {robustResult.baseline.mean_rank}</span>
                    {winner && beat != null && (
                      <div className={cn("mt-0.5", winnerBeatsHold ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-400")}>
                        最稳健策略跑赢持有 <span className="font-semibold tabular-nums">{beat.beating}/{beat.total}</span> 个窗口
                        {excess != null && <>，窗口平均超额 <span className="font-semibold tabular-nums">{pct(excess)}</span></>}
                        {!winnerBeatsHold && "——策略优势不明显，直接持有可能更省心"}
                      </div>
                    )}
                  </div>
                );
              })()}
              {robustResult.ensemble && (
                <div className="rounded-lg border px-3 py-2 text-xs leading-5">
                  <span className="font-medium">前 {robustResult.ensemble.members.length} 名等资金组合</span>
                  <span className="ml-2 text-muted-foreground">
                    {robustResult.ensemble.members.map((m) => STRATEGY_LABELS[m as StrategyName] || m).join(" + ")}
                  </span>
                  <div className="mt-0.5 text-muted-foreground">
                    窗口平均收益 <span className="font-semibold tabular-nums text-foreground">{pct(robustResult.ensemble.mean_return)}</span>
                    {robustResult.ensemble.windows_beating_hold && (
                      <>，跑赢持有 <span className="font-semibold tabular-nums text-foreground">{robustResult.ensemble.windows_beating_hold.beating}/{robustResult.ensemble.windows_beating_hold.total}</span> 窗口</>
                    )}
                    {robustResult.ensemble.beats_winner
                      ? <span className="ml-1 text-emerald-700 dark:text-emerald-300">平衡得分优于单一冠军，分散更稳</span>
                      : <span className="ml-1">得分略低于冠军，但降低了押错单一策略的风险</span>}
                  </div>
                </div>
              )}
              {(robustResult.param_sensitivity?.length ?? 0) > 0 && (
                <div className="rounded-lg border px-3 py-2 text-xs leading-5">
                  <span className="font-medium">参数稳健度</span>
                  <span className="ml-2 text-muted-foreground">关键参数 ±25% 后是否仍跑赢持有</span>
                  <div className="mt-0.5 space-y-0.5">
                    {robustResult.param_sensitivity!.map((s) => (
                      <div key={s.name} className="flex items-center gap-2">
                        <span className="text-muted-foreground">{STRATEGY_LABELS[s.name as StrategyName] || s.name}</span>
                        {s.verdict === "robust" && <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-300">稳健</span>}
                        {s.verdict === "sensitive" && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-700 dark:text-amber-400">敏感——优势可能来自参数巧合</span>}
                        {s.verdict === "no_params" && <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">无关键参数</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">策略</th>
                  {robustResult.windows.map((w) => (
                    <th key={w.label} className="px-2 py-2 text-center font-medium whitespace-nowrap" title={`${w.start} ~ ${w.end}`}>{w.label}</th>
                  ))}
                  <th className="px-2 py-2 text-right font-medium whitespace-nowrap">平均排名</th>
                  <th className="px-2 py-2 text-right font-medium whitespace-nowrap">最差</th>
                  <th className="px-2 py-2 text-right font-medium whitespace-nowrap">波动</th>
                  {robustResult.baseline && (
                    <>
                      <th className="px-2 py-2 text-right font-medium whitespace-nowrap">超额vs持有</th>
                      <th className="px-2 py-2 text-right font-medium whitespace-nowrap">赢持有</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {robustResult.strategies.map((s) => {
                  const isBest = s.name === robustResult.best_strategy;
                  return (
                    <tr key={s.name} className={cn("border-b last:border-0 hover:bg-muted/30", isBest && "bg-primary/10")}>
                      <td className="px-3 py-2 font-medium whitespace-nowrap">
                        {STRATEGY_LABELS[s.name as StrategyName] || s.name}
                        {isBest && <span className="ml-2 text-primary">最稳健</span>}
                      </td>
                      {s.cells.map((c, i) => (
                        <td key={i} className="px-2 py-2 text-center tabular-nums">
                          {c.status === "ok" && c.rank != null ? (
                            <span className={cn(
                              "inline-block min-w-[1.5rem] rounded px-1.5 py-0.5",
                              c.rank === 1 ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 font-semibold"
                                : c.rank <= 3 ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                                : "text-muted-foreground",
                            )} title={c.total_return != null ? `收益 ${pct(c.total_return)} · 亏损 ${pct(c.max_loss)}` : undefined}>
                              {c.rank}
                            </span>
                          ) : (
                            <span className="text-muted-foreground/50">—</span>
                          )}
                        </td>
                      ))}
                      <td className="px-2 py-2 text-right font-semibold tabular-nums">{s.mean_rank}</td>
                      <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{s.worst_rank}</td>
                      <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{s.rank_std}</td>
                      {robustResult.baseline && (
                        <>
                          <td className={cn(
                            "px-2 py-2 text-right tabular-nums",
                            s.mean_excess_vs_hold == null ? "text-muted-foreground/50"
                              : s.mean_excess_vs_hold > 0 ? "text-emerald-700 dark:text-emerald-300"
                              : "text-red-600 dark:text-red-400",
                          )}>
                            {s.mean_excess_vs_hold != null ? pct(s.mean_excess_vs_hold) : "—"}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">
                            {s.windows_beating_hold ? `${s.windows_beating_hold.beating}/${s.windows_beating_hold.total}` : "—"}
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground/80">
            单元格为该策略在对应窗口内的排名（1=最佳，绿色越深越靠前；“—”=该窗口数据不足或回测失败）。平均排名越低越稳健；最差/波动反映一致性。
            超额vs持有 = 各窗口收益减去买入持有的平均值；赢持有 = 平衡得分胜过买入持有的窗口数——跑不赢持有的策略，复杂度本身就是成本。
          </p>
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

              {activeRun.experiment && (
                <div className="rounded-xl border bg-muted/20 px-3 py-2.5 text-[11px] text-muted-foreground">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                    <span>实验版本 {activeRun.experiment.schema_version}</span>
                    <span>指标版本 {activeRun.experiment.metric_version}</span>
                    <span>代码 {activeRun.experiment.code_version.slice(0, 12)}</span>
                    <span>数据 {activeRun.experiment.data_start} → {activeRun.experiment.data_end}</span>
                    <span>基准 {activeRun.experiment.benchmark}</span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground/70 break-all">
                    reproducibility key: {activeRun.experiment.reproducibility_key}
                  </p>
                </div>
              )}

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
