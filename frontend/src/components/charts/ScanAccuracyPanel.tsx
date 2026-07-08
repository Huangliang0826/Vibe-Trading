import { useEffect, useRef, useState } from "react";
import { Loader2, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { api, type ScanAccuracy, type ScanAccuracyHorizon } from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";

const HORIZONS: { key: "fwd_1d" | "fwd_5d" | "fwd_20d"; label: string }[] = [
  { key: "fwd_1d", label: "1 日" },
  { key: "fwd_5d", label: "5 日" },
  { key: "fwd_20d", label: "20 日" },
];

function pct(v: number | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function toneClass(v: number | undefined): string {
  if (v == null || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400";
}

function HorizonCard({ label, h }: { label: string; h: ScanAccuracyHorizon }) {
  if (!h || h.n === 0) {
    return (
      <div className="rounded-xl border bg-card p-4">
        <p className="text-sm font-medium">{label}前瞻收益</p>
        <p className="mt-3 text-xs text-muted-foreground">样本积累中,暂无数据</p>
      </div>
    );
  }
  const spreadPositive = (h.spread ?? 0) > 0;
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{label}前瞻收益</p>
        <span className="text-[11px] text-muted-foreground tabular-nums">{h.n} 样本</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="text-[11px] text-muted-foreground">平均收益</p>
          <p className={cn("text-lg font-bold tabular-nums", toneClass(h.mean))}>{pct(h.mean)}</p>
        </div>
        <div>
          <p className="text-[11px] text-muted-foreground">胜率</p>
          <p className="text-lg font-bold tabular-nums">{h.hit_rate?.toFixed(0)}%</p>
        </div>
      </div>
      {/* Score effectiveness: does the top-score quintile beat the bottom? */}
      <div className="mt-3 border-t pt-3">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>高分组 vs 低分组</span>
          <span className="inline-flex items-center gap-1">
            {spreadPositive ? <TrendingUp className="h-3 w-3 text-red-500" /> : (h.spread ?? 0) < 0 ? <TrendingDown className="h-3 w-3 text-emerald-600" /> : <Minus className="h-3 w-3" />}
            <span className={cn("tabular-nums font-medium", toneClass(h.spread))}>{pct(h.spread)}</span>
          </span>
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[11px] tabular-nums">
          <span className="text-muted-foreground">高分 {pct(h.top_q_mean)}</span>
          <span className="text-muted-foreground">低分 {pct(h.bottom_q_mean)}</span>
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">IC(评分相关性)</span>
          <span className={cn("tabular-nums font-medium", toneClass(h.ic))}>{h.ic?.toFixed(3) ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}

export function ScanAccuracyPanel({ universe }: { universe: string }) {
  const [data, setData] = useState<ScanAccuracy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getScanAccuracy(universe)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError("获取准确率数据失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [universe]);

  // Daily mean-1d line
  useEffect(() => {
    const el = chartRef.current;
    const ts = data?.timeseries ?? [];
    if (!el || ts.length < 2) return;
    const t = getChartTheme();
    const chart = echarts.init(el);
    chart.setOption({
      grid: { left: 44, right: 12, top: 16, bottom: 28 },
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, borderColor: t.tooltipBorder, textStyle: { color: t.tooltipText, fontSize: 11 }, axisPointer: { label: { show: false } } },
      xAxis: { type: "category", data: ts.map((p) => p.date), axisLabel: { fontSize: 10, color: t.textColor }, axisLine: { lineStyle: { color: t.axisColor } } },
      yAxis: { type: "value", axisLabel: { fontSize: 10, color: t.textColor, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.gridColor } } },
      series: [{
        type: "bar", data: ts.map((p) => p.mean_1d),
        itemStyle: { color: (p: { value: number }) => (p.value >= 0 ? t.upColor : t.downColor) },
      }],
    });
    return () => { chart.dispose(); };
  }, [data]);

  if (loading) {
    return <div className="flex h-40 items-center justify-center text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载准确率…</div>;
  }
  if (error || !data) {
    return <p className="py-10 text-center text-xs text-muted-foreground">{error || "暂无数据"}</p>;
  }

  const oneD = data.horizons.fwd_1d;
  const thin = data.total_tracked < 60;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-primary/20 bg-primary/[0.03] px-4 py-2.5">
        <p className="text-xs text-muted-foreground">
          共跟踪 <span className="font-medium text-foreground tabular-nums">{data.total_tracked}</span> 条推荐的真实前瞻收益,用于验证扫描是否有效。
          <span className="ml-1">「高分组 vs 低分组」为正、IC 为正 = 评分越高的股票后续表现越好。</span>
          {thin && <span className="ml-1 text-amber-600 dark:text-amber-400">样本较少,结论仅供参考,会随时间更可靠。</span>}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {HORIZONS.map(({ key, label }) => <HorizonCard key={key} label={label} h={data.horizons[key]} />)}
      </div>

      {data.timeseries.length >= 2 && (
        <div className="rounded-xl border bg-card p-4">
          <p className="text-sm font-medium">每日推荐平均 1 日收益</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">每个交易日全部推荐股票的 1 日前瞻收益均值</p>
          <div ref={chartRef} className="mt-2 h-48 w-full" />
        </div>
      )}

      {oneD.n > 0 && (
        <p className="text-[10px] text-muted-foreground/60">
          IC 为评分与实际收益的秩相关(Spearman);胜率为前瞻收益为正的比例。数据仅供研究参考,不构成投资建议。
        </p>
      )}
    </div>
  );
}
