import React from "react";
import { useEffect, useState, useCallback, useRef } from "react";
import { Cpu, RefreshCw, Loader2, BookOpen, ExternalLink, Sparkles, ChevronDown, ChevronUp, Newspaper, TrendingUp } from "lucide-react";
import { api, type PriceHistoryPeriod, type PriceHistoryBar, type ValuationMetric, type ValuationPeriod, type ValuationPoint, type IndustryReport, type ForecastResponse, type CalibrationResponse, type StrategyResponse, type StrategyMetrics, type TradeSignal, type NewsItem, type QuintileResponse, type FactorScreening, type WalkForwardResponse, type ScanPortfolioResponse, type WatchlistQuote, type SmartTResponse } from "@/lib/api";
import { PriceHistoryChart } from "@/components/charts/PriceHistoryChart";
import { ValuationChart } from "@/components/charts/ValuationChart";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { CalibrationChart } from "@/components/charts/CalibrationChart";
import { StrategyEquityChart } from "@/components/charts/StrategyEquityChart";
import { QuintileChart } from "@/components/charts/QuintileChart";
import { SmartTChart } from "@/components/charts/SmartTChart";
import { useSSE } from "@/hooks/useSSE";
import { cn } from "@/lib/utils";

function inlineMd(text: string): React.ReactNode {
  const parts = text.split(/(\*\*.+?\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i}>{p.slice(2, -2)}</strong>
      : p
  );
}

function cleanReport(raw: string): string {
  let text = raw.replace(/ {2,}/g, " ");
  const headingIdx = text.search(/^#+ /m);
  if (headingIdx > 0) text = text.slice(headingIdx);
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}

function renderMarkdown(md: string): React.ReactNode[] {
  const lines = md.split("\n");
  const elements: React.ReactNode[] = [];
  let idx = 0;
  while (idx < lines.length) {
    const line = lines[idx];
    if (line.trimStart().startsWith("|") && line.includes("|")) {
      const tableLines: string[] = [];
      while (idx < lines.length && lines[idx].trimStart().startsWith("|")) {
        tableLines.push(lines[idx]);
        idx++;
      }
      const dataRows = tableLines.filter((l) => !l.match(/^\s*\|[\s-:|]+\|/));
      const [headerRow, ...bodyRows] = dataRows;
      if (headerRow) {
        const parseCells = (row: string) =>
          row.split("|").slice(1, -1).map((c) => c.trim());
        elements.push(
          <div key={`tbl-${idx}`} className="overflow-x-auto my-3">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b bg-muted/40">
                  {parseCells(headerRow).map((c, ci) => (
                    <th key={ci} className="text-left px-3 py-1.5 text-xs font-medium text-muted-foreground">{inlineMd(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bodyRows.map((row, ri) => (
                  <tr key={ri} className="border-b last:border-b-0">
                    {parseCells(row).map((c, ci) => (
                      <td key={ci} className="px-3 py-1.5 text-xs">{inlineMd(c)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }
    if (!line.trim()) { idx++; continue; }
    if (line.trim() === "---") elements.push(<hr key={idx} className="my-3 border-border" />);
    else if (line.startsWith("### ")) elements.push(<h3 key={idx} className="text-base font-semibold mt-4 mb-2">{inlineMd(line.slice(4))}</h3>);
    else if (line.startsWith("## ")) elements.push(<h2 key={idx} className="text-lg font-bold mt-5 mb-2">{inlineMd(line.slice(3))}</h2>);
    else if (line.startsWith("# ")) elements.push(<h1 key={idx} className="text-xl font-bold mt-6 mb-3">{inlineMd(line.slice(2))}</h1>);
    else if (line.startsWith("- ")) elements.push(<li key={idx} className="ml-4">{inlineMd(line.slice(2))}</li>);
    else elements.push(<p key={idx}>{inlineMd(line)}</p>);
    idx++;
  }
  return elements;
}

const HSTECH_CODE = "03033";
const HSTECH_MARKET = "hk" as const;
const HSTECH_NAME = "恒生科技指数 ETF";

interface AnalysisContext {
  bars: PriceHistoryBar[];
  indices: { name: string; price: number; change_pct: number }[];
  reports: IndustryReport[];
}

function buildAnalysisPrompt(ctx: AnalysisContext): string {
  const today = new Date().toISOString().slice(0, 10);
  const sections: string[] = [];

  // Index levels
  if (ctx.indices.length) {
    const idxLines = ctx.indices.map(i => `- ${i.name}: ${i.price.toFixed(2)}（${i.change_pct >= 0 ? "+" : ""}${i.change_pct.toFixed(2)}%）`).join("\n");
    sections.push(`**港股指数实时行情（${today}）：**\n${idxLines}`);
  }

  // ETF price history
  if (ctx.bars.length >= 2) {
    const last = ctx.bars[ctx.bars.length - 1];
    const first = ctx.bars[0];
    const pct = first.close ? ((last.close - first.close) / first.close * 100).toFixed(2) : "N/A";
    const high = Math.max(...ctx.bars.map(b => b.close)).toFixed(2);
    const low = Math.min(...ctx.bars.map(b => b.close)).toFixed(2);
    const recent10 = ctx.bars.slice(-10).map(b => `${b.date}: ${b.close.toFixed(2)}`).join(", ");
    sections.push(`**恒生科技ETF (03033.HK) 价格数据：**
- 最新收盘价: ${last.close.toFixed(2)}（${last.date}）
- 近一年涨跌幅: ${pct}%（${first.date} ~ ${last.date}）
- 近一年最高: ${high}，最低: ${low}
- 最近10个交易日走势: ${recent10}`);
  }

  // Research reports
  if (ctx.reports.length) {
    const reportLines = ctx.reports.slice(0, 20).map(r => `- [${r.date}] ${r.org}：${r.title}`).join("\n");
    sections.push(`**近期券商研报（共${ctx.reports.length}篇）：**\n${reportLines}`);
  }

  const dataBlock = sections.length
    ? `以下是截至 ${today} 的实时市场数据和研报信息，请务必基于这些最新数据进行分析：\n\n${sections.join("\n\n")}\n`
    : "";

  return `今天是 ${today}。请对恒生科技指数 (HSTECH / Hang Seng TECH Index) 进行全面分析。

${dataBlock}
**基本面分析：**
- 当前估值水平（PE、PB）及其历史分位
- 成分股盈利增长趋势
- 行业结构和权重股表现
- 宏观环境对恒生科技的影响（中美关系、监管政策、利率环境）

**技术面分析（基于上面提供的价格数据）：**
- 当前趋势判断（均线系统、趋势线）
- 关键支撑位和压力位
- 技术指标信号（MACD、RSI、布林带）
- 成交量分析

**投资建议：**
- 综合评级（看多/中性/看空）
- 短期（1-3个月）和中期（6-12个月）展望
- 关键风险因素
- 建议操作策略

请全程用中文回答，结构清晰，数据具体。所有分析必须基于上面提供的最新数据，不要使用过时的数据。直接以标题开头输出报告，不要添加任何开头语、思考过程或过渡语句。`;
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

function fmtRet(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

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

function CalibrationSection({ market, code, context }: { market: "hk"; code: string; context: number }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<CalibrationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getForecastCalibration(market, code, context)
      .then(setData)
      .catch((e) => setError(e?.message || "回测失败"))
      .finally(() => setLoading(false));
  }, [market, code, context]);

  useEffect(() => { if (open) load(); }, [open, context, load]);

  const da = data?.directional_accuracy;
  const skill = data?.skill_vs_random_walk;
  const beatsNaive = skill != null && skill > 0;
  const isSkill = data?.interval_score_skill;
  const beatsInterval = isSkill != null && isSkill > 0;

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        回测校准（模型 vs 朴素基线）
      </button>

      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 走查历史中…（约 10 秒）
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data && data.n_folds > 0 ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Stat label="方向准确率(模型)" value={pct(da?.model)} hint="随机≈50%"
                  tone={da?.model != null ? (da.model > 0.52 ? "good" : "bad") : "neutral"} />
                <Stat label="方向准确率(趋势外推)" value={pct(da?.drift)} hint="对照基线" />
                <Stat label="对随机游走的误差优势"
                  value={skill == null ? "—" : `${skill > 0 ? "+" : ""}${(skill * 100).toFixed(0)}%`}
                  hint={beatsNaive ? "跑赢基线" : "未跑赢基线"} tone={beatsNaive ? "good" : "bad"} />
                <Stat label="80%区间覆盖率" value={pct(data.interval_coverage_80)} hint="校准应≈80%"
                  tone={data.interval_coverage_80 != null ? (data.interval_coverage_80 >= 0.7 ? "good" : "bad") : "neutral"} />
                <Stat label="区间分数优势(vs波动带)"
                  value={isSkill == null ? "—" : `${isSkill > 0 ? "+" : ""}${(isSkill * 100).toFixed(0)}%`}
                  hint={beatsInterval ? "又准又窄✓" : "未胜波动带"} tone={isSkill != null ? (beatsInterval ? "good" : "bad") : "neutral"} />
                <Stat label="平均区间宽度"
                  value={data.mean_interval_width_pct == null ? "—" : `±${(data.mean_interval_width_pct / 2).toFixed(0)}%`}
                  hint="占价·越窄越好" />
              </div>

              <div className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                beatsNaive ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400"
              )}>
                {beatsNaive
                  ? `在 ${data.n_folds} 次历史回放中，模型 MAE 略优于随机游走基线——但请注意优势通常很小，方向预测仍接近抛硬币。`
                  : `在 ${data.n_folds} 次历史回放中，模型未能跑赢"随机游走"这一朴素基线，方向准确率接近 50%。这印证了股价短期不可预测——预测区间仅供参考，切勿据此交易。`}
                {isSkill != null && (
                  <span className="opacity-80">
                    {beatsInterval
                      ? ` 区间分数优于"随机游走+历史波动"带 ${(isSkill * 100).toFixed(0)}%——区间确实又准又窄。`
                      : ` 区间分数也未胜过"随机游走+历史波动"带，说明覆盖率高主要来自合理的宽度，而非额外信息。`}
                  </span>
                )}
              </div>

              {data.conformal && (
                <div className="rounded-xl border bg-card p-3 space-y-2">
                  <p className="text-xs font-semibold text-foreground">共形校正（自适应 CQR · 样本外）</p>
                  <div className="grid grid-cols-3 gap-2">
                    <Stat label="原始覆盖率" value={pct(data.conformal.coverage_raw)}
                      hint={`目标 ${pct(data.conformal.target)}`}
                      tone={Math.abs(data.conformal.coverage_raw - data.conformal.target) <= 0.07 ? "good" : "bad"} />
                    <Stat label="共形校正后" value={pct(data.conformal.coverage_conformal)}
                      hint="有覆盖保证"
                      tone={data.conformal.coverage_conformal >= data.conformal.target - 0.05 ? "good" : "neutral"} />
                    <Stat label="区间宽度变化"
                      value={data.conformal.width_ratio == null ? "—" : `${data.conformal.width_ratio >= 1 ? "+" : ""}${((data.conformal.width_ratio - 1) * 100).toFixed(0)}%`}
                      hint={data.conformal.width_ratio != null && data.conformal.width_ratio >= 1 ? "需加宽" : "可收窄"} />
                  </div>
                </div>
              )}

              {data.overlay && (
                <div>
                  <p className="text-[11px] text-muted-foreground mb-1">最近一折：预测区间 vs 实际走势（{data.bt_horizon} 交易日）</p>
                  <CalibrationChart overlay={data.overlay} />
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground py-4">历史数据不足，无法回测。</p>
          )}
        </div>
      )}
    </div>
  );
}

const STRAT_ROWS: { key: "band_reversion" | "median_trend" | "vol_target" | "buy_and_hold"; label: string }[] = [
  { key: "band_reversion", label: "区间均值回归" },
  { key: "median_trend", label: "中位线趋势" },
  { key: "vol_target", label: "风控叠加(降回撤)" },
  { key: "buy_and_hold", label: "买入持有(基线)" },
];

function StrategySection({ market, code, context }: { market: "hk"; code: string; context: number }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<StrategyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getForecastStrategy(market, code, context)
      .then(setData)
      .catch((e) => setError(e?.message || "回测失败"))
      .finally(() => setLoading(false));
  }, [market, code, context]);

  useEffect(() => { if (open) load(); }, [open, context, load]);

  const metricsOf = (key: string): StrategyMetrics | undefined =>
    key === "buy_and_hold" ? data?.buy_and_hold?.metrics
      : data?.strategies?.[key as "band_reversion" | "median_trend"]?.metrics;

  const beats = data?.beats_buy_and_hold;
  const ready = data && data.strategies && data.buy_and_hold;

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        策略回测（vs 买入持有）
      </button>

      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 模拟交易中…（首次约 30 秒）
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : ready ? (
            <div className="space-y-3">
              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/30 text-muted-foreground text-left">
                      <th className="px-3 py-2 font-medium">策略</th>
                      <th className="px-3 py-2 font-medium text-right">总收益</th>
                      <th className="px-3 py-2 font-medium text-right">年化</th>
                      <th className="px-3 py-2 font-medium text-right">Sharpe</th>
                      <th className="px-3 py-2 font-medium text-right">最大回撤</th>
                      <th className="px-3 py-2 font-medium text-right">胜率</th>
                      <th className="px-3 py-2 font-medium text-right">交易数</th>
                      <th className="px-3 py-2 font-medium text-right">超额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {STRAT_ROWS.map(({ key, label }) => {
                      const m = metricsOf(key);
                      const isBH = key === "buy_and_hold";
                      return (
                        <tr key={key} className={cn("border-b last:border-b-0", isBH && "bg-muted/10")}>
                          <td className="px-3 py-2 font-medium">{label}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmtRet(m?.total_return)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmtRet(m?.annual_return)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{m?.sharpe?.toFixed(2) ?? "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-red-500">{fmtRet(m?.max_drawdown)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{isBH ? "—" : pct(m?.win_rate)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{isBH ? "—" : m?.trade_count ?? "—"}</td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", isBH ? "" : (m && m.excess_return > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"))}>
                            {isBH ? "—" : fmtRet(m?.excess_return)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                beats ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400"
              )}>
                {beats
                  ? `在最近约 ${data.params?.n_days} 个交易日里，有策略扣除 ${data.params?.cost_bps}bps 成本后跑赢了买入持有——但样本有限，谨慎对待，并非可重复的盈利保证。`
                  : `在最近约 ${data.params?.n_days} 个交易日里，两套预测策略扣除 ${data.params?.cost_bps}bps 成本后均未跑赢"买入持有"。这与"预测无方向性 alpha"一致——仅为研究，非投资建议。`}
              </div>

              <div>
                <p className="text-[11px] text-muted-foreground mb-1">净值曲线（初始资金归一）</p>
                <StrategyEquityChart data={data} />
              </div>
            </div>
          ) : data?.error ? (
            <p className="text-xs text-muted-foreground py-4">历史数据不足，无法回测。</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function SmartTSection() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SmartTResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((refresh = false) => {
    setLoading(true);
    setError(null);
    api.getHSTechSmartT("ALL", refresh)
      .then(setData)
      .catch((e) => setError(e?.message || "智能做T回测失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (open && !data && !loading) load(false);
  }, [open, data, loading, load]);

  const signal = data?.current_signal;
  const summary = data?.summary;
  const smart = data?.metrics.smart_t;
  const buyHold = data?.metrics.buy_and_hold;
  const recentEvents = data?.events.slice(-8).reverse() || [];

  return (
    <div className="mt-3 border-t pt-3">
      <div className="flex items-center justify-between gap-2">
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          智能做T策略（被套降成本）
        </button>
        {open && data && (
          <button
            onClick={() => load(true)}
            disabled={loading}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            重新计算
          </button>
        )}
      </div>

      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 智能做T回测中…首次可能较久
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data ? (
            <div className="space-y-3">
              {signal && (
                <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-xs">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-semibold text-foreground">当前建议：{signal.action}</span>
                    <span className="text-muted-foreground">价格 {signal.price.toFixed(3)}</span>
                    <span className="text-muted-foreground">有效成本 {signal.effective_cost.toFixed(3)}</span>
                    <span className="text-muted-foreground">仓位 {pct(signal.position_ratio)}</span>
                    <span className="text-muted-foreground">现金 {pct(signal.cash_ratio)}</span>
                  </div>
                  <p className="mt-1 text-muted-foreground">原因：{signal.reason}</p>
                </div>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Stat label="智能做T收益" value={fmtRet(smart?.total_return)} tone={smart?.total_return != null && smart.total_return >= 0 ? "good" : "bad"} />
                <Stat label="买入持有收益" value={fmtRet(buyHold?.total_return)} />
                <Stat label="智能做T最大回撤" value={fmtRet(smart?.max_drawdown)} tone="bad" />
                <Stat label="买入持有最大回撤" value={fmtRet(buyHold?.max_drawdown)} tone="bad" />
                <Stat label="有效成本降低" value={fmtRet(summary?.cost_reduction)} hint="负数代表成本下降" tone={summary?.cost_reduction != null && summary.cost_reduction < 0 ? "good" : "neutral"} />
                <Stat label="已实现价差" value={summary ? summary.realized_profit.toFixed(4) : "—"} tone={summary?.realized_profit != null && summary.realized_profit >= 0 ? "good" : "bad"} />
                <Stat label="卖出胜率" value={pct(summary?.win_rate)} />
                <Stat label="交易次数" value={summary?.trade_count?.toString() ?? "—"} hint={`卖出 ${summary?.sell_count ?? 0} 次`} />
              </div>

              <div>
                <p className="text-[11px] text-muted-foreground mb-1">净值曲线（初始资金归一）</p>
                <SmartTChart data={data} />
              </div>

              {recentEvents.length > 0 && (
                <div className="overflow-x-auto rounded-xl border">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-muted/30 text-muted-foreground text-left">
                        <th className="px-3 py-2 font-medium">日期</th>
                        <th className="px-3 py-2 font-medium">动作</th>
                        <th className="px-3 py-2 font-medium text-right">价格</th>
                        <th className="px-3 py-2 font-medium text-right">盈亏</th>
                        <th className="px-3 py-2 font-medium text-right">有效成本</th>
                        <th className="px-3 py-2 font-medium">原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentEvents.map((event, idx) => (
                        <tr key={`${event.date}-${event.action}-${idx}`} className="border-b last:border-b-0">
                          <td className="px-3 py-2 tabular-nums">{event.date}</td>
                          <td className="px-3 py-2 font-medium">{event.action}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{event.price.toFixed(3)}</td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", event.pnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{event.pnl.toFixed(4)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{event.effective_cost.toFixed(3)}</td>
                          <td className="px-3 py-2 text-muted-foreground">{event.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ScreeningTable({ items }: { items: FactorScreening[] }) {
  const [expanded, setExpanded] = useState(false);
  const kept = items.filter((f) => f.kept);
  const dropped = items.filter((f) => !f.kept);

  return (
    <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs">
      <button onClick={() => setExpanded((e) => !e)} className="flex items-center gap-1.5 font-medium text-muted-foreground hover:text-foreground transition-colors w-full">
        {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        因子筛选：{kept.length}/{items.length} 通过单调性检验（Spearman ≤ −0.5）
      </button>
      {expanded && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b text-muted-foreground text-left">
                <th className="px-2 py-1 font-medium">因子</th>
                <th className="px-2 py-1 font-medium">Zoo</th>
                <th className="px-2 py-1 font-medium text-right">IR</th>
                <th className="px-2 py-1 font-medium text-right">单调性</th>
                <th className="px-2 py-1 font-medium text-center">Q1→Q5 均值</th>
                <th className="px-2 py-1 font-medium text-center">状态</th>
              </tr>
            </thead>
            <tbody>
              {[...kept, ...dropped].map((f) => (
                <tr key={f.id} className={cn("border-b last:border-b-0", f.kept ? "" : "opacity-40")}>
                  <td className="px-2 py-1 font-mono">{f.id}</td>
                  <td className="px-2 py-1">{f.zoo}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{f.ir.toFixed(3)}</td>
                  <td className={cn("px-2 py-1 text-right tabular-nums", f.mono <= -0.5 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{f.mono.toFixed(2)}</td>
                  <td className="px-2 py-1 text-center tabular-nums text-[10px]">{f.q_means.map((m) => (m * 100).toFixed(1) + "%").join(" → ")}</td>
                  <td className="px-2 py-1 text-center">{f.kept ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CurrentPortfolioSection() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ScanPortfolioResponse | null>(null);
  const [quotes, setQuotes] = useState<Map<string, WatchlistQuote>>(new Map());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getScanPortfolio("hkconnect", "2024-2026")
      .then(async (res) => {
        setData(res);
        const codes = Array.from(new Set([...(res.portfolio.Q1 || []), ...(res.portfolio.Q2 || [])]));
        if (codes.length > 0) {
          try {
            const quoteList = await api.getWatchlistQuote(codes, "hk");
            setQuotes(new Map(quoteList.map((q) => [q.code.toUpperCase(), q])));
          } catch {
            setQuotes(new Map());
          }
        }
      })
      .catch((e) => setError(e?.message || "组合计算失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (open && !data && !loading) load(); }, [open, data, loading, load]);

  const renderBucket = (label: "Q1" | "Q2") => {
    const symbols = data?.portfolio[label] || [];
    return (
      <div className="rounded-xl border overflow-hidden">
        <div className="flex items-center justify-between bg-muted/30 px-3 py-2">
          <span className="text-xs font-semibold text-foreground">{label} 当前组合</span>
          <span className="text-[11px] text-muted-foreground">{symbols.length} 只</span>
        </div>
        <div className="divide-y">
          {symbols.map((symbol) => {
            const quote = quotes.get(symbol.toUpperCase());
            return (
              <div key={`${label}-${symbol}`} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <p className="font-medium text-foreground truncate">{quote?.name || symbol}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">{symbol}</p>
                </div>
                {quote && quote.price > 0 && (
                  <div className="text-right tabular-nums">
                    <p>{quote.price.toFixed(2)}</p>
                    <p className={quote.change_pct >= 0 ? "text-red-500" : "text-emerald-600"}>
                      {quote.change_pct >= 0 ? "+" : ""}{quote.change_pct.toFixed(2)}%
                    </p>
                  </div>
                )}
              </div>
            );
          })}
          {symbols.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">暂无组合数据</div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        当前 Q1 / Q2 组合
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 当前组合计算中…（24 小时缓存）
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data ? (
            <>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                <span>截至 {data.as_of.slice(0, 10)}</span>
                <span>{data.n_stocks} 只股票</span>
                <span>{data.n_factors_used} 个因子</span>
                {data.cached && <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">缓存</span>}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {renderBucket("Q1")}
                {renderBucket("Q2")}
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

function QuintileSection() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<QuintileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getScanQuintile("hstech", "2022-2026", 21, 30, true)
      .then(setData)
      .catch((e) => setError(e?.message || "回测失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (open) load(); }, [open, load]);

  const sp = data?.spread_summary;
  const hasEdge = sp != null && sp.annual_return > 0.05;
  const keptCount = data?.screening?.filter((f) => f.kept).length ?? 0;

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        截面因子分层回测（30 只港股科技）
      </button>

      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 因子单调性筛选 + 分层回测中…（首次约 2~3 分钟）
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data ? (
            <div className="space-y-3">
              {data.screening && <ScreeningTable items={data.screening} />}

              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/30 text-muted-foreground text-left">
                      <th className="px-3 py-2 font-medium">分层</th>
                      <th className="px-3 py-2 font-medium text-right">总收益</th>
                      <th className="px-3 py-2 font-medium text-right">年化</th>
                      <th className="px-3 py-2 font-medium text-right">波动率</th>
                      <th className="px-3 py-2 font-medium text-right">Sharpe</th>
                      <th className="px-3 py-2 font-medium text-right">最大回撤</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["Q1", "Q2", "Q3", "Q4", "Q5"] as const).map((q) => {
                      const s = data.summary[q];
                      if (!s) return null;
                      const isTop = q === "Q1";
                      const isBot = q === "Q5";
                      return (
                        <tr key={q} className={cn("border-b last:border-b-0", isTop && "bg-emerald-500/5", isBot && "bg-red-500/5")}>
                          <td className="px-3 py-2 font-medium">{q}{isTop ? "（最优）" : isBot ? "（最差）" : ""}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmtRet(s.total_return)}</td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", s.annual_return > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(s.annual_return)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{pct(s.annual_vol)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{s.sharpe.toFixed(2)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-red-500">{fmtRet(s.max_drawdown)}</td>
                        </tr>
                      );
                    })}
                    <tr className="border-t-2 bg-indigo-500/5">
                      <td className="px-3 py-2 font-bold">多空 ({data.long_q ?? "Q2"}−{data.short_q ?? "Q5"})</td>
                      <td className="px-3 py-2 text-right tabular-nums font-bold">{fmtRet(sp?.total_return)}</td>
                      <td className={cn("px-3 py-2 text-right tabular-nums font-bold", (sp?.annual_return ?? 0) > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(sp?.annual_return)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{pct(sp?.annual_vol)}</td>
                      <td className="px-3 py-2 text-right tabular-nums font-bold">{sp?.sharpe.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-red-500">{fmtRet(sp?.max_drawdown)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                hasEdge ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400"
              )}>
                {hasEdge
                  ? `精选 ${keptCount} 个单调因子后，在 ${data.n_periods} 个月度换仓周期中，多空（${data.long_q ?? "Q2"}−${data.short_q ?? "Q5"}）年化 ${fmtRet(sp?.annual_return)}、Sharpe ${sp?.sharpe.toFixed(2)}——扣除 ${data.cost_bps}bps 成本后仍有截面 alpha，值得进一步样本外验证。`
                  : `精选 ${keptCount} 个单调因子后，在 ${data.n_periods} 个月度换仓周期中，多空收益仍未能覆盖成本。因子信号在该股票池上的截面区分度不足。`}
              </div>

              <div>
                <p className="text-[11px] text-muted-foreground mb-1">分层净值曲线（{keptCount} 因子 · {data.cost_bps}bps 成本 · 月度换仓 · 等权持仓）</p>
                <QuintileChart data={data} />
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function WalkForwardSection() {
  const [open, setOpen] = useState(false);
  const [universe, setUniverse] = useState<"hstech" | "hkconnect">("hstech");
  const [data, setData] = useState<WalkForwardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [longOnly, setLongOnly] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getScanWalkforward(universe, "2022-2026", 21, 30)
      .then(setData)
      .catch((e) => setError(e?.message || "回测失败"))
      .finally(() => setLoading(false));
  }, [universe]);

  useEffect(() => { if (open && !loading) load(); }, [universe]);
  useEffect(() => { if (open && !data && !loading) load(); }, [open, data, loading, load]);

  const sp = data?.spread_summary;
  const lq = data?.long_q ?? "Q2";
  const longStats = data?.summary[lq];
  const activeStats = longOnly ? longStats : sp;
  const hasEdge = activeStats != null && activeStats.sharpe >= 0.8;

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        样本外验证（Walk-Forward）
      </button>

      {open && (
        <div className="mt-3">
          {/* Universe toggle */}
          <div className="flex items-center gap-1 rounded-lg border bg-muted/30 p-0.5 w-fit mb-3">
            <button
              onClick={() => setUniverse("hstech")}
              className={cn("px-3 py-1 rounded-md text-xs font-medium transition-colors", universe === "hstech" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              HSTECH 30
            </button>
            <button
              onClick={() => setUniverse("hkconnect")}
              className={cn("px-3 py-1 rounded-md text-xs font-medium transition-colors", universe === "hkconnect" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              港股通 500+
            </button>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> {universe === "hkconnect" ? "港股通 500+ 回测中…（首次约 15~20 分钟）" : "滚动样本外回测中…（约 5~8 分钟）"}
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data ? (
            <div className="space-y-3">
              {/* Fold details */}
              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs">
                <p className="font-medium text-muted-foreground mb-2">
                  {data.n_folds} 折滚动验证（{data.is_days} 日样本内筛选 → {data.oos_days} 日样本外测试）
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b text-muted-foreground text-left">
                        <th className="px-2 py-1 font-medium">折</th>
                        <th className="px-2 py-1 font-medium">样本内</th>
                        <th className="px-2 py-1 font-medium">样本外</th>
                        <th className="px-2 py-1 font-medium text-right">入选因子</th>
                        <th className="px-2 py-1 font-medium text-right">OOS 多空</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.folds.map((f) => (
                        <tr key={f.fold} className="border-b last:border-b-0">
                          <td className="px-2 py-1">{f.fold}</td>
                          <td className="px-2 py-1 tabular-nums">{f.is_start.slice(0, 10)} ~ {f.is_end.slice(0, 10)}</td>
                          <td className="px-2 py-1 tabular-nums">{f.oos_start.slice(0, 10)} ~ {f.oos_end.slice(0, 10)}</td>
                          <td className="px-2 py-1 text-right">{f.n_factors_kept}</td>
                          <td className={cn("px-2 py-1 text-right tabular-nums", f.oos_ls_return > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                            {fmtRet(f.oos_ls_return)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Mode toggle */}
              <div className="flex items-center gap-1 rounded-lg border bg-muted/30 p-0.5 w-fit">
                <button
                  onClick={() => setLongOnly(true)}
                  className={cn("px-3 py-1 rounded-md text-xs font-medium transition-colors", longOnly ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground")}
                >
                  纯多（{lq}）
                </button>
                <button
                  onClick={() => setLongOnly(false)}
                  className={cn("px-3 py-1 rounded-md text-xs font-medium transition-colors", !longOnly ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground")}
                >
                  多空（{lq}−{data.short_q ?? "Q5"}）
                </button>
              </div>

              {/* Summary stats table */}
              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/30 text-muted-foreground text-left">
                      <th className="px-3 py-2 font-medium">分层（OOS）</th>
                      <th className="px-3 py-2 font-medium text-right">总收益</th>
                      <th className="px-3 py-2 font-medium text-right">年化</th>
                      <th className="px-3 py-2 font-medium text-right">波动率</th>
                      <th className="px-3 py-2 font-medium text-right">Sharpe</th>
                      <th className="px-3 py-2 font-medium text-right">最大回撤</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["Q1", "Q2", "Q3", "Q4", "Q5"] as const).map((q) => {
                      const s = data.summary[q];
                      if (!s) return null;
                      const sq = data.short_q ?? "Q5";
                      const isLong = q === lq;
                      const isShort = q === sq;
                      return (
                        <tr key={q} className={cn("border-b last:border-b-0", isLong && "bg-emerald-500/5", !longOnly && isShort && "bg-red-500/5")}>
                          <td className="px-3 py-2 font-medium">{q}{isLong ? "（多头）" : !longOnly && isShort ? "（空头）" : ""}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmtRet(s.total_return)}</td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", s.annual_return > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(s.annual_return)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{pct(s.annual_vol)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{s.sharpe.toFixed(2)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-red-500">{fmtRet(s.max_drawdown)}</td>
                        </tr>
                      );
                    })}
                    {!longOnly && (
                      <tr className="border-t-2 bg-indigo-500/5">
                        <td className="px-3 py-2 font-bold">多空 ({lq}−{data.short_q ?? "Q5"})</td>
                        <td className="px-3 py-2 text-right tabular-nums font-bold">{fmtRet(sp?.total_return)}</td>
                        <td className={cn("px-3 py-2 text-right tabular-nums font-bold", (sp?.annual_return ?? 0) > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(sp?.annual_return)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{pct(sp?.annual_vol)}</td>
                        <td className="px-3 py-2 text-right tabular-nums font-bold">{sp?.sharpe.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-red-500">{fmtRet(sp?.max_drawdown)}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Verdict */}
              <div className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                hasEdge ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400"
              )}>
                {longOnly
                  ? (hasEdge
                    ? `纯样本外 ${data.n_periods} 个换仓周期，纯多（${lq}）年化 ${fmtRet(longStats?.annual_return)}、Sharpe ${longStats?.sharpe.toFixed(2)}、最大回撤 ${fmtRet(longStats?.max_drawdown)}——无需做空，alpha 信号独立成立。`
                    : `纯样本外 ${data.n_periods} 个换仓周期，纯多（${lq}）Sharpe ${longStats?.sharpe.toFixed(2)} < 0.8——纯多信号偏弱，可考虑加入空头对冲。`)
                  : (hasEdge
                    ? `纯样本外 ${data.n_periods} 个换仓周期，多空（${lq}−${data.short_q ?? "Q5"}）年化 ${fmtRet(sp?.annual_return)}、Sharpe ${sp?.sharpe.toFixed(2)}——无前视偏差，截面 alpha 信号可信。`
                    : `纯样本外 ${data.n_periods} 个换仓周期，多空（${lq}−${data.short_q ?? "Q5"}）Sharpe ${sp?.sharpe.toFixed(2)} < 0.8——信号不够稳健。`)}
              </div>

              {/* Equity curve */}
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">样本外净值曲线（仅 OOS 区间拼接）</p>
                <QuintileChart data={{ ...data, screening: undefined }} />
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

const SEGMENT_COLORS: Record<string, string> = {
  恒生科技: "bg-primary/10 text-primary",
  港股科技: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  港股策略: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
};

function buildSummaryPrompt(reports: IndustryReport[]): string {
  const lines = reports.slice(0, 40).map((r) => `- [${r.date}] ${r.org}：${r.title}`).join("\n");
  return `以下是最近两个月与恒生科技指数相关的 ${reports.length} 篇券商研报标题：

${lines}

请严格按以下格式输出总结：

**一、观点倾向分布**

| 倾向 | 数量 | 代表报告 |
|------|------|----------|
| **看多/积极** | ~X 篇 | 列举2-3个代表性观点摘要 |
| **谨慎/看空** | ~X 篇 | 列举2-3个代表性观点摘要 |
| **中性/分析** | ~X 篇 | 列举2-3个代表性观点摘要 |

**二、主要看多逻辑**
- （列2-3条）

**三、主要看空/谨慎逻辑**
- （列2-3条）

**四、核心分歧点**
- （列1-2条，券商之间观点分歧最大的问题）

请全程用中文回答，简洁扼要，直接输出总结内容，不要添加开头语或额外段落，不要用分隔线（---）。`;
}

function buildNewsSummaryPrompt(items: NewsItem[]): string {
  const lines = items.slice(0, 30).map((n) => `- [${n.time}] ${n.title}${n.summary ? `：${n.summary.slice(0, 80)}` : ""}`).join("\n");
  return `以下是今日与恒生科技指数相关的 ${items.length} 条新闻：

${lines}

请严格按以下格式输出总结：

**一、今日核心动态**
- （列3-5条最重要的市场动态）

**二、市场情绪判断**
- 整体情绪：看多/中性/偏空
- 依据：（1-2句）

**三、关注焦点**
- （列2-3条市场最关注的主题或事件）

**四、潜在风险提示**
- （列1-2条）

请全程用中文回答，简洁扼要，直接输出总结内容，不要添加开头语或额外段落。`;
}

function todayDateKey(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function newsDateKey(time: string): string {
  const text = String(time || "");
  const m = text.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (m) {
    return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  }
  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) {
    const y = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const day = String(parsed.getDate()).padStart(2, "0");
    return `${y}-${month}-${day}`;
  }
  return "";
}

function filterTodayNews(items: NewsItem[]): NewsItem[] {
  const today = todayDateKey();
  return items.filter((item) => newsDateKey(item.time) === today);
}

type Tab = "forecast" | "news" | "report" | "research";
const SECTION_TABS: { key: Tab; label: string }[] = [
  { key: "forecast", label: "走势预测" },
  { key: "news", label: "新闻" },
  { key: "report", label: "分析报告" },
  { key: "research", label: "投研库" },
];

type CardView = "price" | ValuationMetric;

const VIEW_TABS: { key: CardView; label: string }[] = [
  { key: "price", label: "价格" },
  { key: "pe", label: "市盈率" },
  { key: "pb", label: "市净率" },
  { key: "mktcap", label: "市值" },
];

export function HSTech() {
  // Section tab state
  const [tab, setTab] = useState<Tab>("forecast");

  // Chart view state
  const [view, setView] = useState<CardView>("price");
  const [period, setPeriod] = useState<PriceHistoryPeriod>("1Y");
  const [bars, setBars] = useState<PriceHistoryBar[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [stockName, setStockName] = useState(HSTECH_NAME);

  // Valuation state
  const [valPeriod, setValPeriod] = useState<ValuationPeriod>("5Y");
  const [valPoints, setValPoints] = useState<ValuationPoint[]>([]);
  const [valLoading, setValLoading] = useState(false);

  // Forecast state
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  // Trade signal state
  type SignalStrategy = "median_trend" | "band_reversion";
  const [allTrades, setAllTrades] = useState<Record<string, TradeSignal[]>>({});
  const [signalStrategy, setSignalStrategy] = useState<SignalStrategy>("median_trend");
  const [tradesLoading, setTradesLoading] = useState(false);
  const trades = allTrades[signalStrategy] || [];

  // Analysis report state
  const [report, setReport] = useState<string>(() => {
    try { return cleanReport(localStorage.getItem("hstech-report") || ""); } catch { return ""; }
  });
  const [reportLoading, setReportLoading] = useState(false);
  const reportRef = useRef("");
  const { connect, disconnect } = useSSE();

  // Research report library state
  const [reports, setReports] = useState<IndustryReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [reportsRange, setReportsRange] = useState<{ begin: string; end: string } | null>(null);

  // LLM summary state
  const [summary, setSummary] = useState<string>(() => {
    try { return localStorage.getItem("hstech-summary") || ""; } catch { return ""; }
  });
  const [summaryLoading, setSummaryLoading] = useState(false);
  const summaryRef = useRef("");
  const { connect: connectSummary, disconnect: disconnectSummary } = useSSE();

  // News state
  const [news, setNews] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState<string | null>(null);

  // News LLM summary state
  const [newsSummary, setNewsSummary] = useState<string>(() => {
    try { return localStorage.getItem(`hstech-news-summary-${todayDateKey()}`) || ""; } catch { return ""; }
  });
  const [newsSummaryLoading, setNewsSummaryLoading] = useState(false);
  const newsSummaryRef = useRef("");
  const { connect: connectNewsSummary, disconnect: disconnectNewsSummary } = useSSE();

  // Fetch price history
  useEffect(() => {
    if (view !== "price") return;
    let cancelled = false;
    setChartLoading(true);
    setChartError(null);
    api.getWatchlistHistory(HSTECH_CODE, period, HSTECH_MARKET)
      .then((res) => {
        if (cancelled) return;
        setBars(res.bars);
        if (res.name) setStockName(res.name);
      })
      .catch((e) => {
        if (cancelled) return;
        setChartError(e instanceof Error ? e.message : "获取走势失败");
        setBars([]);
      })
      .finally(() => { if (!cancelled) setChartLoading(false); });
    return () => { cancelled = true; };
  }, [period, view]);

  // Fetch valuation series
  useEffect(() => {
    if (view === "price") return;
    let cancelled = false;
    setValLoading(true);
    setValPoints([]);
    api.getWatchlistValuation(HSTECH_CODE, HSTECH_MARKET, view, valPeriod)
      .then((res) => { if (!cancelled) setValPoints(res.points); })
      .catch(() => { if (!cancelled) setValPoints([]); })
      .finally(() => { if (!cancelled) setValLoading(false); });
    return () => { cancelled = true; };
  }, [view, valPeriod]);

  const loadForecast = useCallback((nocache = 0) => {
    setForecastLoading(true);
    setForecastError(null);
    api.getForecast(HSTECH_MARKET, HSTECH_CODE, 3, 512, nocache)
      .then(setForecast)
      .catch((e) => setForecastError(e?.message || "预测失败"))
      .finally(() => setForecastLoading(false));
  }, []);

  useEffect(() => { loadForecast(); }, [loadForecast]);

  const loadTrades = useCallback(() => {
    setTradesLoading(true);
    api.getForecastStrategy(HSTECH_MARKET, HSTECH_CODE, 512)
      .then((res) => {
        setAllTrades({
          median_trend: res.strategies?.median_trend?.trades || [],
          band_reversion: res.strategies?.band_reversion?.trades || [],
        });
      })
      .catch(() => setAllTrades({}))
      .finally(() => setTradesLoading(false));
  }, []);

  const generateReport = useCallback(async () => {
    if (reportLoading) return;
    setReportLoading(true);
    reportRef.current = "";
    setReport("");

    try {
      // Fetch fresh index data to include in prompt
      let hkIndices: { name: string; price: number; change_pct: number }[] = [];
      try {
        const allIndices = await api.getMarketIndices();
        hkIndices = allIndices
          .filter((i: { market: string }) => i.market === "港股")
          .map((i: { name: string; price: number; change_pct: number }) => ({ name: i.name, price: i.price, change_pct: i.change_pct }));
      } catch { /* proceed without index data */ }

      const prompt = buildAnalysisPrompt({ bars, indices: hkIndices, reports });

      const session = await api.createSession("恒生科技分析");
      const sid = session.session_id;

      connect(api.sseUrl(sid), {
        text_delta: (d) => {
          reportRef.current += String(d.delta || "");
          setReport(reportRef.current);
        },
        "attempt.completed": () => {
          setReportLoading(false);
          disconnect();
          const cleaned = cleanReport(reportRef.current);
          reportRef.current = cleaned;
          setReport(cleaned);
          try { localStorage.setItem("hstech-report", cleaned); } catch {}
        },
        "attempt.failed": (d) => {
          setReportLoading(false);
          disconnect();
          if (!reportRef.current) {
            setReport(`分析生成失败：${String(d.error || "未知错误")}`);
          }
        },
        heartbeat: () => {},
        reconnect: () => {},
      });

      await api.sendMessage(sid, prompt);
    } catch (e) {
      setReportLoading(false);
      setReport(`请求失败：${e instanceof Error ? e.message : "未知错误"}`);
    }
  }, [reportLoading, bars, reports, connect, disconnect]);

  const loadNews = useCallback(() => {
    setNewsLoading(true);
    setNewsError(null);
    api.getHSTechNews()
      .then((res) => setNews(res.items || []))
      .catch((e) => setNewsError(e?.message || "获取新闻失败"))
      .finally(() => setNewsLoading(false));
  }, []);

  useEffect(() => { loadNews(); }, [loadNews]);

  const generateNewsSummary = useCallback(async () => {
    const todayNews = filterTodayNews(news);
    if (newsSummaryLoading || todayNews.length === 0) return;
    setNewsSummaryLoading(true);
    newsSummaryRef.current = "";
    setNewsSummary("");

    try {
      const session = await api.createSession("恒生科技新闻总结");
      const sid = session.session_id;

      connectNewsSummary(api.sseUrl(sid), {
        text_delta: (d) => {
          newsSummaryRef.current += String(d.delta || "");
          setNewsSummary(newsSummaryRef.current);
        },
        "attempt.completed": () => {
          setNewsSummaryLoading(false);
          disconnectNewsSummary();
          try { localStorage.setItem(`hstech-news-summary-${todayDateKey()}`, newsSummaryRef.current); } catch {}
        },
        "attempt.failed": (d) => {
          setNewsSummaryLoading(false);
          disconnectNewsSummary();
          if (!newsSummaryRef.current) {
            setNewsSummary(`总结生成失败：${String(d.error || "未知错误")}`);
          }
        },
        heartbeat: () => {},
        reconnect: () => {},
      });

      await api.sendMessage(sid, buildNewsSummaryPrompt(todayNews));
    } catch (e) {
      setNewsSummaryLoading(false);
      setNewsSummary(`请求失败：${e instanceof Error ? e.message : "未知错误"}`);
    }
  }, [newsSummaryLoading, news, connectNewsSummary, disconnectNewsSummary]);

  const loadReports = useCallback(() => {
    setReportsLoading(true);
    setReportsError(null);
    api.getHSTechReports()
      .then((res) => {
        setReports(res.reports || []);
        setReportsRange({ begin: res.begin, end: res.end });
        if (res.error) setReportsError(res.error);
      })
      .catch((e) => setReportsError(e?.message || "获取研报失败"))
      .finally(() => setReportsLoading(false));
  }, []);

  useEffect(() => { loadReports(); }, [loadReports]);

  const generateSummary = useCallback(async () => {
    if (summaryLoading || reports.length === 0) return;
    setSummaryLoading(true);
    summaryRef.current = "";
    setSummary("");

    try {
      const session = await api.createSession("恒生科技研报总结");
      const sid = session.session_id;

      connectSummary(api.sseUrl(sid), {
        text_delta: (d) => {
          summaryRef.current += String(d.delta || "");
          setSummary(summaryRef.current);
        },
        "attempt.completed": () => {
          setSummaryLoading(false);
          disconnectSummary();
          try { localStorage.setItem("hstech-summary", summaryRef.current); } catch {}
        },
        "attempt.failed": (d) => {
          setSummaryLoading(false);
          disconnectSummary();
          if (!summaryRef.current) {
            setSummary(`总结生成失败：${String(d.error || "未知错误")}`);
          }
        },
        heartbeat: () => {},
        reconnect: () => {},
      });

      await api.sendMessage(sid, buildSummaryPrompt(reports));
    } catch (e) {
      setSummaryLoading(false);
      setSummary(`请求失败：${e instanceof Error ? e.message : "未知错误"}`);
    }
  }, [summaryLoading, reports, connectSummary, disconnectSummary]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { disconnect(); disconnectSummary(); disconnectNewsSummary(); };
  }, [disconnect, disconnectSummary, disconnectNewsSummary]);

  const todayNewsCount = filterTodayNews(news).length;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-bold">恒生科技</h1>
        </div>
      </div>

      {/* Chart card */}
      <div className="rounded-2xl border bg-card p-4">
        <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
          <span className="text-sm font-semibold text-foreground">
            {stockName}
            <span className="font-mono text-xs text-muted-foreground ml-1">{HSTECH_CODE}</span>
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
              loading={chartLoading}
              height={300}
              showRisk
            />
            {chartError && <p className="text-xs text-red-500 dark:text-red-400 mt-2">{chartError}</p>}
          </>
        ) : (
          <ValuationChart
            points={valPoints}
            metric={view}
            period={valPeriod}
            onPeriodChange={setValPeriod}
            loading={valLoading}
            height={300}
          />
        )}
      </div>

      {/* Section tabs */}
      <div className="flex gap-1 border-b">
        {SECTION_TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
              key === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Forecast tab */}
      {tab === "forecast" && (
        <div className="rounded-2xl border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold text-foreground">走势预测</h2>
              <p className="text-[11px] text-muted-foreground">
              TimesFM 3 个月不确定性锥{forecast?.conformal_q != null && " · 已共形校正"} · 仅供参考，非投资建议
            </p>
            </div>
            <div className="flex items-center gap-2">
              {forecast && !forecast.model && (
                <span className="text-[10px] text-yellow-600 dark:text-yellow-400">
                  {forecast.model_error === "timesfm_not_installed" ? "模型未安装，仅显示基线" : "模型不可用"}
                </span>
              )}
              {Object.keys(allTrades).length > 0 ? (
                <div className="inline-flex items-center rounded-lg border text-xs overflow-hidden">
                  {([["median_trend", "中位线趋势"], ["band_reversion", "区间均值回归"]] as const).map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setSignalStrategy(key)}
                      className={cn(
                        "px-2.5 py-1.5 transition-colors",
                        signalStrategy === key
                          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-medium"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted"
                      )}
                    >
                      {label}
                    </button>
                  ))}
                  <button
                    onClick={loadTrades}
                    disabled={tradesLoading}
                    className="px-2 py-1.5 border-l text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                  >
                    {tradesLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  </button>
                </div>
              ) : (
                <button
                  onClick={loadTrades}
                  disabled={tradesLoading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
                >
                  {tradesLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TrendingUp className="h-3.5 w-3.5" />}
                  {tradesLoading ? "加载中..." : "显示信号"}
                </button>
              )}
              <button
                onClick={() => loadForecast(1)}
                disabled={forecastLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
              >
                {forecastLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                {forecastLoading ? "计算中..." : "重新预测"}
              </button>
            </div>
          </div>

          {forecastLoading ? (
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground" style={{ height: 300 }}>
              <Loader2 className="h-5 w-5 animate-spin" /> 预测计算中…
            </div>
          ) : forecastError ? (
            <p className="text-xs text-red-500 dark:text-red-400">{forecastError}</p>
          ) : forecast ? (
            <>
              <ForecastChart data={forecast} height={300} trades={trades.length > 0 ? trades : undefined} />
              <CalibrationSection market={HSTECH_MARKET} code={HSTECH_CODE} context={512} />
              <StrategySection market={HSTECH_MARKET} code={HSTECH_CODE} context={512} />
              <SmartTSection />
              <CurrentPortfolioSection />
              <QuintileSection />
              <WalkForwardSection />
            </>
          ) : null}
        </div>
      )}

      {/* News tab */}
      {tab === "news" && (
        <div className="rounded-2xl border bg-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-foreground">恒生科技相关新闻</h2>
            <div className="flex items-center gap-2">
              <button
                onClick={generateNewsSummary}
                disabled={newsSummaryLoading || todayNewsCount === 0}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
              >
                {newsSummaryLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {newsSummaryLoading ? "总结中..." : newsSummary ? "重新总结今日" : "AI 总结今日"}
              </button>
              <button
                onClick={loadNews}
                disabled={newsLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
              >
                {newsLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                刷新
              </button>
            </div>
          </div>

          {(newsSummary || newsSummaryLoading) && (
            <div className="rounded-xl border bg-muted/30 p-4 mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span className="text-xs font-medium text-primary">AI 今日新闻总结</span>
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed text-sm">
                {renderMarkdown(newsSummary)}
                {newsSummaryLoading && (
                  <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
                )}
              </div>
            </div>
          )}

          {newsError && (
            <p className="text-xs text-red-500 dark:text-red-400 mb-3">{newsError}</p>
          )}

          {!newsLoading && news.length > 0 && todayNewsCount === 0 && (
            <p className="text-xs text-muted-foreground mb-3">今日暂无新闻，AI 总结仅在有当日新闻时可用。</p>
          )}

          {newsLoading && news.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : news.length === 0 ? (
            <div className="rounded-xl border border-dashed py-12 flex flex-col items-center gap-3 text-center">
              <Newspaper className="h-8 w-8 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">暂无相关新闻</p>
            </div>
          ) : (
            <div className="space-y-3">
              {news.map((item, i) => (
                <div key={i} className="rounded-xl border p-3 hover:bg-muted/20 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      {item.url ? (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium hover:text-primary transition-colors inline-flex items-center gap-1"
                        >
                          {item.title}
                          <ExternalLink className="h-3 w-3 shrink-0 opacity-40" />
                        </a>
                      ) : (
                        <p className="text-sm font-medium">{item.title}</p>
                      )}
                      {item.summary && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{item.summary}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-[10px] text-muted-foreground/70">
                    {item.time && <span>{item.time}</span>}
                    {item.source && <span>{item.source}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Report tab */}
      {tab === "report" && (
        <div className="rounded-2xl border bg-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-foreground">基本面 + 技术面分析报告</h2>
            <button
              onClick={generateReport}
              disabled={reportLoading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
            >
              {reportLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {reportLoading ? "生成中..." : report ? "重新生成" : "生成报告"}
            </button>
          </div>

          {!report && !reportLoading ? (
            <div className="rounded-xl border border-dashed py-12 flex flex-col items-center gap-3 text-center">
              <Cpu className="h-8 w-8 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">点击「生成报告」获取恒生科技指数的分析</p>
              <p className="text-xs text-muted-foreground/60">报告由智能体生成，包含基本面、技术面分析和投资建议</p>
            </div>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed text-sm">
              {renderMarkdown(report)}
              {reportLoading && (
                <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
              )}
            </div>
          )}
        </div>
      )}

      {/* Research tab */}
      {tab === "research" && (
        <div className="rounded-2xl border bg-card p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">投研库</h2>
              {reportsRange && (
                <span className="text-[10px] text-muted-foreground/60">
                  {reportsRange.begin} ~ {reportsRange.end}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={generateSummary}
                disabled={summaryLoading || reports.length === 0}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
              >
                {summaryLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                {summaryLoading ? "总结中..." : summary ? "重新总结" : "AI 总结"}
              </button>
              <button
                onClick={loadReports}
                disabled={reportsLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition disabled:opacity-50"
              >
                {reportsLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                刷新
              </button>
            </div>
          </div>

          {reportsError && (
            <p className="text-xs text-red-500 dark:text-red-400 mb-3">{reportsError}</p>
          )}

          {/* AI Summary */}
          {(summary || summaryLoading) && (
            <div className="rounded-xl border bg-muted/30 p-4 mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span className="text-xs font-medium text-primary">AI 观点总结</span>
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed text-sm">
                {renderMarkdown(summary)}
                {summaryLoading && (
                  <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
                )}
              </div>
            </div>
          )}

          {/* Report table */}
          {reportsLoading && reports.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : reports.length === 0 ? (
            <div className="rounded-xl border border-dashed py-12 flex flex-col items-center gap-3 text-center">
              <BookOpen className="h-8 w-8 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">暂无恒生科技相关研报</p>
            </div>
          ) : (
            <div className="rounded-xl border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                    <th className="text-left px-3 py-2 font-medium">日期</th>
                    <th className="text-left px-3 py-2 font-medium">机构</th>
                    <th className="text-left px-3 py-2 font-medium">标题</th>
                    <th className="text-left px-3 py-2 font-medium">分类</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r, i) => (
                    <tr key={i} className="border-b last:border-b-0 hover:bg-muted/20 transition-colors">
                      <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{r.date}</td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap">{r.org}</td>
                      <td className="px-3 py-2 text-xs">
                        {r.url ? (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:text-primary transition-colors inline-flex items-center gap-1"
                          >
                            {r.title}
                            <ExternalLink className="h-3 w-3 shrink-0 opacity-40" />
                          </a>
                        ) : r.title}
                      </td>
                      <td className="px-3 py-2">
                        {r.segment && (
                          <span className={cn(
                            "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
                            SEGMENT_COLORS[r.segment] || "bg-muted text-muted-foreground"
                          )}>
                            {r.segment}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
