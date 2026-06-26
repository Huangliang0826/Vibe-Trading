import { useEffect, useState, useCallback } from "react";
import { LineChart, Loader2, AlertTriangle, ChevronDown, ChevronUp, TrendingUp } from "lucide-react";
import { api, type WatchlistMarket, type ForecastResponse, type CalibrationResponse, type StrategyResponse, type StrategyMetrics, type RobustnessResponse, type HSTechBestStrategyResponse } from "@/lib/api";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { CalibrationChart } from "@/components/charts/CalibrationChart";
import { StrategyEquityChart } from "@/components/charts/StrategyEquityChart";
import { cn } from "@/lib/utils";

function loadList(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

// ── metric tile ──────────────────────────────────────────────────────────────

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

// ── calibration section (lazy) ───────────────────────────────────────────────

function CalibrationSection({ market, code, context }: { market: WatchlistMarket; code: string; context: number }) {
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

  // Re-run when context changes while the section is open.
  useEffect(() => { if (open) load(); }, [open, context, load]);

  const toggle = () => setOpen((o) => !o);

  const da = data?.directional_accuracy;
  const skill = data?.skill_vs_random_walk;
  const beatsNaive = skill != null && skill > 0;
  const isSkill = data?.interval_score_skill;          // 区间分数 skill
  const beatsInterval = isSkill != null && isSkill > 0;

  return (
    <div className="mt-3 border-t pt-3">
      <button onClick={toggle} className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        回测校准（模型 vs 朴素基线）
      </button>

      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> 走查历史中…（每只约 10 秒）
            </div>
          ) : error ? (
            <p className="text-xs text-red-500">{error}</p>
          ) : data && data.n_folds > 0 ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Stat
                  label="方向准确率(模型)"
                  value={pct(da?.model)}
                  hint="随机≈50%"
                  tone={da?.model != null ? (da.model > 0.52 ? "good" : "bad") : "neutral"}
                />
                <Stat label="方向准确率(趋势外推)" value={pct(da?.drift)} hint="对照基线" />
                <Stat
                  label="对随机游走的误差优势"
                  value={skill == null ? "—" : `${skill > 0 ? "+" : ""}${(skill * 100).toFixed(0)}%`}
                  hint={beatsNaive ? "跑赢基线" : "未跑赢基线"}
                  tone={beatsNaive ? "good" : "bad"}
                />
                <Stat
                  label="80%区间覆盖率"
                  value={pct(data.interval_coverage_80)}
                  hint="校准应≈80%"
                  tone={data.interval_coverage_80 != null ? (data.interval_coverage_80 >= 0.7 ? "good" : "bad") : "neutral"}
                />
                <Stat
                  label="区间分数优势(vs波动带)"
                  value={isSkill == null ? "—" : `${isSkill > 0 ? "+" : ""}${(isSkill * 100).toFixed(0)}%`}
                  hint={beatsInterval ? "又准又窄✓" : "未胜波动带"}
                  tone={isSkill != null ? (beatsInterval ? "good" : "bad") : "neutral"}
                />
                <Stat
                  label="平均区间宽度"
                  value={data.mean_interval_width_pct == null ? "—" : `±${(data.mean_interval_width_pct / 2).toFixed(0)}%`}
                  hint="占价·越窄越好"
                />
              </div>

              {/* Honest verdict */}
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
                {data.context_used != null && (
                  <span className="opacity-70"> 每折输入约 {data.context_used} 个交易日。</span>
                )}
              </div>

              {/* Conformal (CQR) calibration: raw vs guaranteed-coverage band */}
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
                  <p className="text-[11px] text-muted-foreground">
                    {data.conformal.coverage_raw < data.conformal.target - 0.05
                      ? `模型原始 80% 区间过度自信（实际仅 ${pct(data.conformal.coverage_raw)}）；自适应共形层据近期误差把区间${data.conformal.width_ratio != null && data.conformal.width_ratio >= 1 ? `加宽约 ${((data.conformal.width_ratio - 1) * 100).toFixed(0)}%` : "调整"}，使真实覆盖率回到 ${pct(data.conformal.coverage_conformal)} ≈ 目标——这一步把"经验校准"升级为"有保证的区间"，风控叠加才真正可信。`
                      : `模型原始区间覆盖率已接近目标；共形层据近期波动微调宽度（×${data.conformal.width_ratio?.toFixed(2)}），维持 ${pct(data.conformal.coverage_conformal)} 覆盖。`}
                  </p>
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

// ── strategy backtest section (lazy) ─────────────────────────────────────────

function fmtRet(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

const STRAT_ROWS: { key: "band_reversion" | "median_trend" | "vol_target" | "buy_and_hold"; label: string }[] = [
  { key: "band_reversion", label: "区间均值回归" },
  { key: "median_trend", label: "中位线趋势" },
  { key: "vol_target", label: "风控叠加(降回撤)" },
  { key: "buy_and_hold", label: "买入持有(基线)" },
];

function StrategySection({ market, code, context }: { market: WatchlistMarket; code: string; context: number }) {
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
              {/* Metrics table */}
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

              {/* Honest verdict */}
              <div className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                beats ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400"
              )}>
                {beats
                  ? `在最近约 ${data.params?.n_days} 个交易日里，有策略扣除 ${data.params?.cost_bps}bps 成本后跑赢了买入持有——但样本有限，谨慎对待，并非可重复的盈利保证。`
                  : `在最近约 ${data.params?.n_days} 个交易日里，两套预测策略扣除 ${data.params?.cost_bps}bps 成本后均未跑赢"买入持有"。这与"预测无方向性 alpha"一致——所谓"大概率盈利"并不被回测支持。区间均值回归通常回撤更小，但代价是长期空仓、总收益更低。仅为研究，非投资建议。`}
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

// ── per-stock card ───────────────────────────────────────────────────────────

function ForecastCard({ market, code, context }: { market: WatchlistMarket; code: string; context: number }) {
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bestStrategy, setBestStrategy] = useState<HSTechBestStrategyResponse | null>(null);
  const [bestStrategyLoading, setBestStrategyLoading] = useState(false);
  const [bestStrategyError, setBestStrategyError] = useState<string | null>(null);
  const trades = bestStrategy?.best?.trades || [];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getForecast(market, code, 3, context)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e?.message || "预测失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [market, code, context]);

  const loadBestStrategy = useCallback((refresh = false) => {
    setBestStrategyLoading(true);
    setBestStrategyError(null);
    api.getForecastBestPaperStrategy(market, code, refresh)
      .then(setBestStrategy)
      .catch((e) => setBestStrategyError(e?.message || "最优策略回测失败"))
      .finally(() => setBestStrategyLoading(false));
  }, [market, code]);

  useEffect(() => { loadBestStrategy(false); }, [loadBestStrategy]);

  return (
    <div className="rounded-2xl border bg-card p-4">
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
            onClick={() => loadBestStrategy(true)}
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
          <CalibrationSection market={market} code={code} context={context} />
          <StrategySection market={market} code={code} context={context} />
        </>
      ) : null}
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────

// ── cross-stock robustness panel ─────────────────────────────────────────────

function RobustnessPanel({ hk, us, context }: { hk: string[]; us: string[]; context: number }) {
  const [data, setData] = useState<RobustnessResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const codes = [
    ...hk.map((c) => `hk:${c.toUpperCase()}`),
    ...us.map((c) => `us:${c.toUpperCase()}`),
  ].join(",");

  const run = () => {
    setLoading(true);
    setError(null);
    api.getStrategyRobustness(codes, context)
      .then(setData)
      .catch((e) => setError(e?.message || "测试失败"))
      .finally(() => setLoading(false));
  };

  const s = data?.summary;
  const ex = s?.excess;
  const anyEdge = ex && (ex.band_reversion.pct_positive ?? 0) > 0.6;

  return (
    <div className="rounded-2xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-foreground">跨股稳健性测试</h3>
          <p className="text-[11px] text-muted-foreground">把策略跑遍自选股，看超额收益是否可复现（而非单股运气）</p>
        </div>
        <button
          onClick={run}
          disabled={loading || !codes}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border hover:border-foreground/30 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LineChart className="h-3.5 w-3.5" />}
          {loading ? "测试中…（每股约 30 秒）" : "运行测试"}
        </button>
      </div>

      {error && <p className="text-xs text-red-500 mt-3">{error}</p>}

      {s && s.n > 0 && ex && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <Stat label="区间均值回归 跑赢持有" value={pct(ex.band_reversion.pct_positive)}
              hint={`中位超额 ${fmtRet(ex.band_reversion.median)}`}
              tone={(ex.band_reversion.pct_positive ?? 0) > 0.5 ? "good" : "bad"} />
            <Stat label="中位线趋势 跑赢持有" value={pct(ex.median_trend.pct_positive)}
              hint={`中位超额 ${fmtRet(ex.median_trend.median)}`}
              tone={(ex.median_trend.pct_positive ?? 0) > 0.5 ? "good" : "bad"} />
            <Stat label="风控叠加 回撤更浅" value={pct(s.vol_target_dd_better_pct)}
              hint={`中位超额 ${fmtRet(ex.vol_target.median)}`}
              tone={(s.vol_target_dd_better_pct ?? 0) >= 0.6 ? "good" : "neutral"} />
          </div>

          <div className={cn("rounded-lg border px-3 py-2 text-xs",
            anyEdge ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
              : "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400")}>
            {anyEdge
              ? `在 ${s.n} 只股票里，区间均值回归多数跑赢买入持有——但样本有限，仍需更多标的与样本外验证。`
              : `在 ${s.n} 只股票里，没有任何预测策略能稳定跑赢买入持有（命中率≈抛硬币），印证"无可复现的方向性 alpha"。` +
                `${(s.vol_target_dd_better_pct ?? 0) >= 0.6 ? ` 但"风控叠加"在 ${pct(s.vol_target_dd_better_pct)} 的股票上回撤更浅——这是模型唯一可复现的价值：降风险而非提收益。` : ""}`}
          </div>

          {/* Per-name table */}
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/30 text-muted-foreground text-left">
                  <th className="px-3 py-2 font-medium">股票</th>
                  <th className="px-3 py-2 font-medium text-right">买入持有</th>
                  <th className="px-3 py-2 font-medium text-right">均值回归超额</th>
                  <th className="px-3 py-2 font-medium text-right">趋势超额</th>
                  <th className="px-3 py-2 font-medium text-right">风控超额</th>
                </tr>
              </thead>
              <tbody>
                {s.per_name.map((r) => (
                  <tr key={r.code} className="border-b last:border-b-0">
                    <td className="px-3 py-2 font-medium">{r.code}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmtRet(r.bh_return)}</td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", r.band_reversion_excess > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(r.band_reversion_excess)}</td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", r.median_trend_excess > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(r.median_trend_excess)}</td>
                    <td className={cn("px-3 py-2 text-right tabular-nums", r.vol_target_excess > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{fmtRet(r.vol_target_excess)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data?.errors && data.errors.length > 0 && (
            <p className="text-[11px] text-muted-foreground">跳过 {data.errors.length} 只（数据不足/获取失败）</p>
          )}
        </div>
      )}
    </div>
  );
}

const CONTEXT_OPTIONS: { label: string; value: number }[] = [
  { label: "全部历史", value: 0 },
  { label: "5 年", value: 1260 },
  { label: "2 年", value: 512 },
  { label: "1 年", value: 252 },
];

export function Forecast() {
  const [hk, setHk] = useState<string[]>([]);
  const [us, setUs] = useState<string[]>([]);
  const [context, setContext] = useState(512); // 默认 2 年：回测各折等长可比 + 近期 regime

  const sync = useCallback(() => {
    setHk(loadList("watchlist-hk"));
    setUs(loadList("watchlist-us"));
  }, []);

  useEffect(() => {
    sync();
    // Re-sync when returning to the tab (watchlist edited on 总览).
    window.addEventListener("focus", sync);
    return () => window.removeEventListener("focus", sync);
  }, [sync]);

  const total = hk.length + us.length;

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
          <span className="text-xs text-muted-foreground">输入历史</span>
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

      {/* Honesty disclaimer */}
      <div className="mb-6 rounded-xl border border-yellow-500/30 bg-yellow-500/5 px-4 py-3">
        <p className="text-xs text-yellow-700 dark:text-yellow-400 flex items-start gap-2">
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            股价接近随机游走，单变量模型对 3 个月走势<b>几乎没有真实预测能力</b>。此处展示的是
            <b>不确定性区间（非单一预测线）</b>、<b>朴素基线对照</b>，以及<b>回测校准</b>结果——
            多数情况下模型并不能跑赢随机游走。<b>仅为模型外推，绝非投资建议。</b>
          </span>
        </p>
      </div>

      {total === 0 ? (
        <div className="rounded-2xl border border-dashed bg-card/50 py-12 flex flex-col items-center gap-2 text-center">
          <LineChart className="h-7 w-7 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">在「总览」页添加港股/美股自选后，此处显示走势预测</p>
        </div>
      ) : (
        <div className="space-y-4">
          <RobustnessPanel hk={hk} us={us} context={context} />
          {hk.map((code) => <ForecastCard key={`hk-${code}`} market="hk" code={code.toUpperCase()} context={context} />)}
          {us.map((code) => <ForecastCard key={`us-${code}`} market="us" code={code.toUpperCase()} context={context} />)}
        </div>
      )}
    </div>
  );
}
