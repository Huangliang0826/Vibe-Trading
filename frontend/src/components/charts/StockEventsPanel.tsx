import { useEffect, useState } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { api, type StockEventsResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

// 股数 → 亿股 / 万股
function shares(v: number): string {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿股`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(0)} 万股`;
  return `${n.toFixed(0)} 股`;
}

function wan(v: number): string {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)} 亿`;
  return `${n.toFixed(0)} 万`;
}

export function StockEventsPanel({ code }: { code: string }) {
  const [data, setData] = useState<StockEventsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getStockEvents(code)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError("获取事件数据失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code]);

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载事件…
      </div>
    );
  }
  if (error || !data) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{error || "暂无数据"}</p>;
  }

  const { upcoming, history } = data.lockup;
  const { records, seats } = data.dragon_tiger;

  return (
    <div className="space-y-5 py-1">
      {/* 未来解禁预警 */}
      <section>
        <h4 className="mb-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5" /> 未来 90 天限售解禁
        </h4>
        {upcoming.length === 0 ? (
          <p className="rounded-lg border bg-card px-3 py-2.5 text-xs text-muted-foreground">未来 90 天无待解禁 ✓</p>
        ) : (
          <div className="space-y-1.5">
            {upcoming.map((u, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs">
                <div>
                  <span className="tabular-nums font-medium text-amber-600 dark:text-amber-400">{u.date}</span>
                  <span className="ml-2 text-muted-foreground">{u.type}</span>
                </div>
                <div className="tabular-nums text-right">
                  <span className="font-medium">{shares(u.shares)}</span>
                  {u.ratio ? <span className="ml-1.5 text-muted-foreground">占流通 {Number(u.ratio).toFixed(1)}%</span> : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 龙虎榜 */}
      <section>
        <h4 className="mb-1.5 text-xs text-muted-foreground">龙虎榜(近 90 日)</h4>
        {records.length === 0 ? (
          <p className="rounded-lg border bg-card px-3 py-2.5 text-xs text-muted-foreground">近 90 日未上榜</p>
        ) : (
          <div className="space-y-2">
            {records.map((r, i) => (
              <div key={i} className="rounded-lg border bg-card px-3 py-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="tabular-nums font-medium">{r.date}</span>
                  <span className={cn("tabular-nums font-medium",
                    r.net_buy_wan >= 0 ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                    净买入 {wan(r.net_buy_wan)}
                  </span>
                </div>
                <p className="mt-0.5 text-muted-foreground">{r.reason}</p>
              </div>
            ))}
            {seats.buy.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-2">
                {([["买入席位", seats.buy], ["卖出席位", seats.sell]] as const).map(([label, list]) => (
                  <div key={label}>
                    <p className="mb-1 text-[11px] text-muted-foreground">{label} TOP{list.length}</p>
                    <div className="space-y-1">
                      {list.map((s, i) => (
                        <div key={i} className="flex items-center justify-between rounded-md border bg-card px-2 py-1 text-[11px]">
                          <span className="truncate max-w-[60%]">{s.name}</span>
                          <span className={cn("tabular-nums",
                            s.net_wan >= 0 ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                            净 {wan(s.net_wan)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* 历史解禁 */}
      {history.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs text-muted-foreground">历史解禁(近 {Math.min(4, history.length)} 次)</h4>
          <div className="flex flex-wrap gap-1.5">
            {history.slice(0, 4).map((h, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-[11px] tabular-nums">
                <span className="text-muted-foreground">{h.date}</span>
                <span>{shares(h.shares)}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <p className="text-[10px] text-muted-foreground/60">
        数据来源:东方财富(公开数据)· 仅呈现客观榜单事实,不构成投资建议
      </p>
    </div>
  );
}
