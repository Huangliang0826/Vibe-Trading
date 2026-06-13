import { useEffect, useState } from "react";
import { Radar, AlertTriangle, RefreshCw, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

interface ScanCandidate {
  symbol: string;
  score: number;
  provider_id: string;
  attribution: string;
  detail: Record<string, number>;
}

interface ScanData {
  universe: string;
  asof: string;
  providers: string[];
  candidates: ScanCandidate[];
  warnings: string[];
}

interface TrackingRecord {
  symbol: string;
  score: number;
  asof: string;
  entry_date?: string;
  entry_price?: number;
  fwd_1d?: number;
  fwd_5d?: number;
  fwd_20d?: number;
}

interface CalibrationData {
  total_tracked: number;
  filled: number;
  alerts: { metric: string; message: string }[];
  ok: boolean;
}

export function Scanner() {
  const [data, setData] = useState<ScanData | null>(null);
  const [tracking, setTracking] = useState<Map<string, TrackingRecord>>(new Map());
  const [calibration, setCalibration] = useState<CalibrationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.getScanLatest()
      .then((scan) => {
        setData(scan);
        api.getScanTracking(scan.asof)
          .then((t) => {
            const map = new Map<string, TrackingRecord>();
            for (const r of t.records || []) map.set(r.symbol, r);
            setTracking(map);
          })
          .catch(() => setTracking(new Map()));
        api.getScanCalibration()
          .then(setCalibration)
          .catch(() => {});
      })
      .catch((e) => setError(e?.message || "Failed to load scan"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载扫描结果…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-muted-foreground">
        <AlertTriangle className="h-8 w-8" />
        <p className="text-sm">{error || "暂无扫描结果"}</p>
        <p className="text-xs">
          运行 <code className="bg-muted px-1.5 py-0.5 rounded text-xs">scan run</code> 生成首次扫描
        </p>
        <button onClick={load} className="mt-2 text-xs text-primary hover:underline">
          重试
        </button>
      </div>
    );
  }

  const ranked = data.candidates;
  const maxScore = ranked.length > 0 ? ranked[0].score : 100;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Radar className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold">机会扫描</h1>
            <p className="text-xs text-muted-foreground">
              {data.universe.toUpperCase()} · 截至 {data.asof} · {ranked.length} 只股票
            </p>
          </div>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border hover:border-foreground/20"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>

      {/* Calibration alerts */}
      {calibration && !calibration.ok && calibration.alerts.map((a, i) => (
        <div key={i} className="mb-4 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3">
          <p className="text-xs text-red-600 dark:text-red-400 flex items-start gap-2">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            {a.message}
          </p>
        </div>
      ))}

      {/* Warnings */}
      {data.warnings.length > 0 && (
        <div className="mb-4 rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-4 py-3">
          {data.warnings.map((w, i) => (
            <p key={i} className="text-xs text-yellow-600 dark:text-yellow-400 flex items-start gap-2">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              {w}
            </p>
          ))}
        </div>
      )}

      {/* Leaderboard table */}
      <div className="rounded-lg border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/30">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground w-12">#</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">股票</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">综合评分</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground hidden sm:table-cell">归因</th>
              {tracking.size > 0 && (
                <>
                  <th className="text-right px-4 py-3 font-medium text-muted-foreground hidden lg:table-cell">1日</th>
                  <th className="text-right px-4 py-3 font-medium text-muted-foreground hidden lg:table-cell">5日</th>
                  <th className="text-right px-4 py-3 font-medium text-muted-foreground hidden lg:table-cell">20日</th>
                </>
              )}
              <th className="text-left px-4 py-3 font-medium text-muted-foreground hidden md:table-cell">因子贡献</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((c, i) => (
              <tr
                key={c.symbol}
                className={cn(
                  "border-b last:border-b-0 transition-colors hover:bg-muted/20",
                  i < 3 && "bg-primary/[0.02]"
                )}
              >
                <td className="px-4 py-3 tabular-nums text-muted-foreground">
                  {i + 1}
                </td>
                <td className="px-4 py-3 font-mono font-semibold">
                  {c.symbol}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-20 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${(c.score / maxScore) * 100}%` }}
                      />
                    </div>
                    <span className="tabular-nums text-xs font-medium w-10 text-right">
                      {c.score.toFixed(1)}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground hidden sm:table-cell max-w-[200px] truncate">
                  {c.attribution}
                </td>
                {tracking.size > 0 && (
                  <>
                    <td className="px-4 py-3 text-right hidden lg:table-cell">
                      <ReturnCell value={tracking.get(c.symbol)?.fwd_1d} />
                    </td>
                    <td className="px-4 py-3 text-right hidden lg:table-cell">
                      <ReturnCell value={tracking.get(c.symbol)?.fwd_5d} />
                    </td>
                    <td className="px-4 py-3 text-right hidden lg:table-cell">
                      <ReturnCell value={tracking.get(c.symbol)?.fwd_20d} />
                    </td>
                  </>
                )}
                <td className="px-4 py-3 hidden md:table-cell">
                  <FactorChips detail={c.detail} />
                </td>
              </tr>
            ))}
            {ranked.length === 0 && (
              <tr>
                <td colSpan={tracking.size > 0 ? 8 : 5} className="px-4 py-8 text-center text-muted-foreground text-sm">
                  暂无排名数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer info */}
      <p className="mt-3 text-xs text-muted-foreground/60">
        数据源: {data.providers.join(", ")} · 因子门槛 α_t ≥ 3.0 · 排名仅供研究参考
        {calibration && ` · 已跟踪 ${calibration.filled}/${calibration.total_tracked} 样本`}
      </p>
    </div>
  );
}

function ReturnCell({ value }: { value?: number }) {
  if (value === undefined || value === null) return <span className="text-xs text-muted-foreground/40">—</span>;
  const color = value >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400";
  return <span className={cn("text-xs tabular-nums font-medium", color)}>{value >= 0 ? "+" : ""}{value.toFixed(2)}%</span>;
}

function FactorChips({ detail }: { detail: Record<string, number> }) {
  const entries = Object.entries(detail)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);
  if (entries.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([name, value]) => (
        <span
          key={name}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
        >
          <span className="truncate max-w-[80px]">{name}</span>
          <span className="tabular-nums font-medium">{value.toFixed(1)}</span>
        </span>
      ))}
    </div>
  );
}
