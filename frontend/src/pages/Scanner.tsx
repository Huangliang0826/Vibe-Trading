import { useEffect, useState, useCallback } from "react";
import { Radar, AlertTriangle, RefreshCw, Loader2, ChevronLeft, ChevronRight, Calendar } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const PROVIDER_META: Record<string, { label: string; color: string }> = {
  factor_rank: { label: "因子", color: "bg-blue-500/10 text-blue-600 dark:text-blue-400" },
  anomaly: { label: "异常", color: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
};

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

type RankChange = { delta: number; isNew: boolean };

function computeRankChanges(
  current: ScanCandidate[],
  previous: ScanCandidate[] | null,
): Map<string, RankChange> {
  const map = new Map<string, RankChange>();
  if (!previous || previous.length === 0) return map;
  const prevRank = new Map(previous.map((c, i) => [c.symbol, i + 1]));
  current.forEach((c, i) => {
    const curRank = i + 1;
    const prev = prevRank.get(c.symbol);
    if (prev === undefined) {
      map.set(c.symbol, { delta: 0, isNew: true });
    } else {
      map.set(c.symbol, { delta: prev - curRank, isNew: false });
    }
  });
  return map;
}

export function Scanner() {
  const [data, setData] = useState<ScanData | null>(null);
  const [prevData, setPrevData] = useState<ScanData | null>(null);
  const [tracking, setTracking] = useState<Map<string, TrackingRecord>>(new Map());
  const [calibration, setCalibration] = useState<CalibrationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [dateIdx, setDateIdx] = useState(0);

  const loadScan = useCallback((asof?: string) => {
    setLoading(true);
    setError(null);
    const fetchScan = asof ? api.getScanByDate(asof) : api.getScanLatest();
    fetchScan
      .then((scan) => {
        setData(scan);
        api.getScanTracking(scan.asof)
          .then((t) => {
            const map = new Map<string, TrackingRecord>();
            for (const r of t.records || []) map.set(r.symbol, r);
            setTracking(map);
          })
          .catch(() => setTracking(new Map()));
        api.getScanCalibration().then(setCalibration).catch(() => {});
      })
      .catch((e) => setError(e?.message || "Failed to load scan"))
      .finally(() => setLoading(false));
  }, []);

  const loadPrevious = useCallback((prevAsof: string) => {
    api.getScanByDate(prevAsof).then(setPrevData).catch(() => setPrevData(null));
  }, []);

  useEffect(() => {
    api.getScanDates().then((r) => {
      setDates(r.dates);
      if (r.dates.length > 0) {
        loadScan(r.dates[0]);
        if (r.dates.length > 1) loadPrevious(r.dates[1]);
      } else {
        setLoading(false);
      }
    }).catch(() => {
      loadScan();
    });
  }, [loadScan, loadPrevious]);

  const navigateDate = (dir: -1 | 1) => {
    const newIdx = dateIdx + dir;
    if (newIdx < 0 || newIdx >= dates.length) return;
    setDateIdx(newIdx);
    loadScan(dates[newIdx]);
    const prevIdx = newIdx + 1;
    if (prevIdx < dates.length) {
      loadPrevious(dates[prevIdx]);
    } else {
      setPrevData(null);
    }
  };

  const refreshScan = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const previous = data;
      const scan = await api.runScan(data?.universe ?? "sp500", 20);
      setData(scan);
      if (previous) setPrevData(previous.asof === scan.asof ? prevData : previous);
      setDateIdx(0);
      const [dateResult, trackingResult, calibrationResult] = await Promise.all([
        api.getScanDates(),
        api.getScanTracking(scan.asof).catch(() => ({ records: [] })),
        api.getScanCalibration().catch(() => null),
      ]);
      setDates(dateResult.dates);
      const nextTracking = new Map<string, TrackingRecord>();
      for (const record of trackingResult.records || []) nextTracking.set(record.symbol, record);
      setTracking(nextTracking);
      if (calibrationResult) setCalibration(calibrationResult);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新机会失败");
    } finally {
      setRefreshing(false);
    }
  };

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
        <p className="text-xs">点击更新生成最新扫描结果</p>
        <button
          onClick={() => void refreshScan()}
          disabled={refreshing}
          aria-label="更新机会"
          className="mt-2 inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-primary disabled:opacity-50"
        >
          {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {refreshing ? "更新中" : "更新机会"}
        </button>
      </div>
    );
  }

  const allCandidates = data.candidates;
  const ranked = filter ? allCandidates.filter(c => c.provider_id === filter) : allCandidates;
  const maxScore = allCandidates.length > 0 ? allCandidates[0].score : 100;
  const providerCounts = allCandidates.reduce<Record<string, number>>((acc, c) => {
    acc[c.provider_id] = (acc[c.provider_id] || 0) + 1;
    return acc;
  }, {});
  const rankChanges = computeRankChanges(ranked, prevData?.candidates ?? null);
  const isLatest = dateIdx === 0;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Radar className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold">机会扫描</h1>
            <p className="text-xs text-muted-foreground">
              {data.universe.toUpperCase()} · {ranked.length} 只股票
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Date navigator */}
          {dates.length > 1 && (
            <div className="flex items-center gap-1 border border-border rounded px-1">
              <button
                onClick={() => navigateDate(1)}
                disabled={dateIdx >= dates.length - 1}
                className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="text-xs tabular-nums px-1 flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                {data.asof}
              </span>
              <button
                onClick={() => navigateDate(-1)}
                disabled={dateIdx <= 0}
                className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {dates.length <= 1 && (
            <span className="text-xs tabular-nums text-muted-foreground flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {data.asof}
            </span>
          )}
          <button
            onClick={() => void refreshScan()}
            disabled={refreshing}
            aria-label="更新机会"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border hover:border-foreground/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {refreshing ? "更新中" : "更新"}
          </button>
        </div>
      </div>

      {/* Non-latest banner */}
      {!isLatest && (
        <div className="mb-4 rounded-lg border border-blue-500/30 bg-blue-500/5 px-4 py-2 flex items-center justify-between">
          <p className="text-xs text-blue-600 dark:text-blue-400">
            正在查看历史扫描 ({data.asof})，共 {dates.length} 期
          </p>
          <button
            onClick={() => { setDateIdx(0); loadScan(dates[0]); if (dates.length > 1) loadPrevious(dates[1]); }}
            className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
          >
            回到最新 →
          </button>
        </div>
      )}

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

      {/* Provider filter */}
      {Object.keys(providerCounts).length > 1 && (
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => setFilter(null)}
            className={cn(
              "text-xs px-2.5 py-1 rounded-full border transition-colors",
              !filter ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            全部 ({allCandidates.length})
          </button>
          {Object.entries(providerCounts).map(([pid, count]) => {
            const meta = PROVIDER_META[pid] || { label: pid, color: "bg-muted text-muted-foreground" };
            return (
              <button
                key={pid}
                onClick={() => setFilter(filter === pid ? null : pid)}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-full border transition-colors",
                  filter === pid ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground"
                )}
              >
                {meta.label} ({count})
              </button>
            );
          })}
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
            {ranked.map((c, i) => {
              const change = rankChanges.get(c.symbol);
              return (
                <tr
                  key={c.symbol}
                  className={cn(
                    "border-b last:border-b-0 transition-colors hover:bg-muted/20",
                    i < 3 && "bg-primary/[0.02]"
                  )}
                >
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">
                    <div className="flex items-center gap-1">
                      {i + 1}
                      <RankBadge change={change} />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono font-semibold">{c.symbol}</span>
                      <ProviderBadge providerId={c.provider_id} />
                    </div>
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
              );
            })}
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
        {dates.length > 1 && ` · ${dates.length} 期历史`}
      </p>
    </div>
  );
}

function RankBadge({ change }: { change?: RankChange }) {
  if (!change) return null;
  if (change.isNew) {
    return <span className="text-[9px] font-bold text-emerald-500">新</span>;
  }
  if (change.delta === 0) return null;
  if (change.delta > 0) {
    return <span className="text-[9px] tabular-nums font-bold text-green-500">↑{change.delta}</span>;
  }
  return <span className="text-[9px] tabular-nums font-bold text-red-500">↓{Math.abs(change.delta)}</span>;
}

function ProviderBadge({ providerId }: { providerId: string }) {
  const meta = PROVIDER_META[providerId];
  if (!meta) return null;
  return (
    <span className={cn("text-[9px] px-1.5 py-0.5 rounded-full font-medium", meta.color)}>
      {meta.label}
    </span>
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
