import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type StockCapitalResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

// 元 → 亿 / 万, compact
function yi(v: number): string {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(0)} 万`;
  return `${n.toFixed(0)}`;
}

function signed(v: number): string {
  const n = Number(v) || 0;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={cn(
        "mt-0.5 text-lg font-bold tabular-nums tracking-tight",
        tone === "up" && "text-red-500 dark:text-red-400",
        tone === "down" && "text-emerald-600 dark:text-emerald-400",
      )}>{value}</p>
      {sub && <p className="text-[11px] text-muted-foreground tabular-nums">{sub}</p>}
    </div>
  );
}

export function CapitalFlowPanel({ code }: { code: string }) {
  const [data, setData] = useState<StockCapitalResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getStockCapital(code)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError("获取资金面数据失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code]);

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载资金面…
      </div>
    );
  }
  if (error || !data) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{error || "暂无数据"}</p>;
  }

  const margin = data.margin[0];
  const marginPrev = data.margin[1];
  const marginChg = margin && marginPrev && marginPrev.rzye
    ? (margin.rzye / marginPrev.rzye - 1) * 100 : 0;
  const holder = data.holders[0];
  const hasFlow = data.fund_flow.length > 0;

  return (
    <div className="space-y-4 py-1">
      {/* Stat row */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {margin && (
          <Stat
            label="融资余额"
            value={yi(margin.rzye)}
            sub={`环比 ${signed(marginChg)} · ${margin.date}`}
            tone={marginChg >= 0 ? "up" : "down"}
          />
        )}
        {holder && (
          <Stat
            label="股东户数"
            value={holder.holder_num.toLocaleString()}
            sub={`环比 ${signed(holder.change_ratio)} · ${holder.date}`}
            // 减少 = 筹码集中,用红(偏多)标记
            tone={holder.change_ratio <= 0 ? "up" : "down"}
          />
        )}
        {hasFlow && (
          <Stat
            label="近 20 日主力净流入"
            value={yi(data.fund_flow_20d_main_net)}
            tone={data.fund_flow_20d_main_net >= 0 ? "up" : "down"}
          />
        )}
      </div>

      {/* Block trades */}
      {data.block_trades.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs text-muted-foreground">大宗交易(近 {Math.min(5, data.block_trades.length)} 笔)</h4>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/30 text-muted-foreground">
                  <th className="px-2.5 py-1.5 text-left font-normal">日期</th>
                  <th className="px-2.5 py-1.5 text-right font-normal">成交价</th>
                  <th className="px-2.5 py-1.5 text-right font-normal">溢价</th>
                  <th className="px-2.5 py-1.5 text-right font-normal">金额</th>
                </tr>
              </thead>
              <tbody>
                {data.block_trades.slice(0, 5).map((b, i) => (
                  <tr key={i} className="border-b last:border-b-0">
                    <td className="px-2.5 py-1.5 tabular-nums">{b.date}</td>
                    <td className="px-2.5 py-1.5 text-right tabular-nums">{b.price}</td>
                    <td className={cn("px-2.5 py-1.5 text-right tabular-nums",
                      b.premium_pct >= 0 ? "text-red-500 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                      {signed(b.premium_pct)}
                    </td>
                    <td className="px-2.5 py-1.5 text-right tabular-nums">{yi(b.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Dividends */}
      {data.dividends.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs text-muted-foreground">分红送转(近 {Math.min(4, data.dividends.length)} 次)</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.dividends.slice(0, 4).map((d, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-[11px] tabular-nums">
                <span className="text-muted-foreground">{d.date}</span>
                <span>派 {d.bonus_rmb}元</span>
                {d.transfer_ratio > 0 && <span className="text-primary">转{d.transfer_ratio}</span>}
                {d.bonus_ratio > 0 && <span className="text-primary">送{d.bonus_ratio}</span>}
              </span>
            ))}
          </div>
        </section>
      )}

      <p className="text-[10px] text-muted-foreground/60">
        数据来源:东方财富(公开数据)· 仅供研究参考,不构成投资建议
      </p>
    </div>
  );
}
