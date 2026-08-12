import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RefreshCw, ShieldAlert, Play, CircleCheck, CircleAlert } from "lucide-react";
import { api, type TradingSnapshot, type LiveStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PaperAutoTradePanel } from "@/components/paper-trading/PaperAutoTradePanel";

const POLL_MS = 5000;

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function money(v: unknown): string {
  const n = num(v);
  return n === null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}
// Alpaca returns enum-prefixed strings like "OrderSide.BUY" / "AccountStatus.ACTIVE".
function clean(v: unknown): string {
  if (v === null || v === undefined) return "—";
  const s = String(v);
  return s.includes(".") ? s.split(".").pop() || s : s;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-xl border bg-card px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 text-lg font-semibold tabular-nums",
        tone === "good" && "text-emerald-600 dark:text-emerald-400",
        tone === "bad" && "text-red-500")}>{value}</div>
    </div>
  );
}

export function LivePaperTab() {
  const [snap, setSnap] = useState<TradingSnapshot | null>(null);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, st] = await Promise.all([api.getTradingSnapshot(), api.getLiveStatus().catch(() => null)]);
      setSnap(s);
      if (st) setStatus(st);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(true);
    timer.current = setInterval(() => refresh(false), POLL_MS);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [refresh]);

  const halted = !!status?.global_halted;

  const toggleHalt = async () => {
    const confirmMsg = halted
      ? "恢复自主交易？runner 将可以在下一个 tick 继续下单。"
      : "紧急停止：立即阻止自主 runner 的下一次交易 tick。确定？";
    if (!window.confirm(confirmMsg)) return;
    setBusy(true);
    try {
      if (halted) await api.resumeLive(undefined, undefined, "用户从监控页恢复");
      else await api.haltLive(undefined, undefined, "用户从监控页停止");
      await refresh(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const account = (snap?.account ?? {}) as Record<string, unknown>;
  const positions = snap?.positions ?? [];
  const orders = snap?.open_orders ?? [];
  const connected = !!snap?.connected;

  return (
    <div className="space-y-4">
      <div className="app-panel space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="app-panel-title">Paper 账户 · Alpaca 沙盒</h2>
          <p className="text-[11px] text-muted-foreground">
            实时前向模拟交易(非历史回测)。主机隔离,永不动真钱。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]",
            connected ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
            {connected ? <CircleCheck className="h-3.5 w-3.5" /> : <CircleAlert className="h-3.5 w-3.5" />}
            {connected ? (snap?.is_paper ? "已连接 · Paper" : "已连接") : "未连接"}
          </span>
          <button
            onClick={() => refresh(true)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
          <button
            onClick={toggleHalt}
            disabled={busy}
            className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50",
              halted
                ? "bg-emerald-600 text-white hover:opacity-90"
                : "bg-red-600 text-white hover:opacity-90")}
            title={halted ? "恢复自主交易" : "立即停止自主 runner 的下一次交易 tick"}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : halted ? <Play className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
            {halted ? "已停止 · 恢复" : "紧急停止"}
          </button>
        </div>
      </div>

      {halted && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">
          全局 kill switch 已触发——自主 runner 不会再开始新的交易 tick,直到点击恢复。
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">{error}</div>
      )}

      {!connected && !loading && !error && (
        <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-6 text-center text-xs text-muted-foreground">
          未连接 Alpaca paper 账户。请在 <span className="font-mono">~/.vibe-trading/alpaca.json</span> 填入 paper API key/secret。
          {snap?.account_error && <div className="mt-1 text-red-500">{snap.account_error}</div>}
        </div>
      )}

      {connected && (
        <>
          {/* Account summary */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Stat label="现金" value={money(account.cash)} />
            <Stat label="净值" value={money(account.equity)} />
            <Stat label="可用购买力" value={money(account.buying_power)} />
            <Stat label="组合市值" value={money(account.portfolio_value)} />
            <Stat label="账户状态" value={clean(account.status)}
              tone={account.trading_blocked ? "bad" : "good"} />
          </div>

          {/* Positions */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">持仓 ({positions.length})</h3>
            {positions.length === 0 ? (
              <p className="text-xs text-muted-foreground">当前无持仓。</p>
            ) : (
              <div className="app-table-shell">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">标的</th>
                      <th className="px-3 py-2 text-right font-medium">数量</th>
                      <th className="px-3 py-2 text-right font-medium">均价</th>
                      <th className="px-3 py-2 text-right font-medium">市值</th>
                      <th className="px-3 py-2 text-right font-medium">浮动盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p, i) => {
                      const pos = p as Record<string, unknown>;
                      // Alpaca connector field names: quantity / average_cost / unrealized_pnl.
                      const qty = num(pos.quantity ?? pos.qty);
                      const upl = num(pos.unrealized_pnl ?? pos.unrealized_pl);
                      return (
                        <tr key={String(pos.symbol ?? i)} className="border-b last:border-0">
                          <td className="px-3 py-2 font-medium">{clean(pos.symbol)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{qty === null ? "—" : qty.toFixed(4).replace(/\.?0+$/, "")}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{money(pos.average_cost ?? pos.avg_entry_price)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{money(pos.market_value)}</td>
                          <td className={cn("px-3 py-2 text-right tabular-nums",
                            upl != null && upl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                            {money(upl)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Open orders */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">挂单 ({orders.length})</h3>
            {orders.length === 0 ? (
              <p className="text-xs text-muted-foreground">当前无挂单。</p>
            ) : (
              <div className="app-table-shell">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">标的</th>
                      <th className="px-3 py-2 text-left font-medium">方向</th>
                      <th className="px-3 py-2 text-right font-medium">数量</th>
                      <th className="px-3 py-2 text-left font-medium">类型</th>
                      <th className="px-3 py-2 text-left font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o, i) => {
                      const ord = o as Record<string, unknown>;
                      const side = clean(ord.side);
                      return (
                        <tr key={String(ord.order_id ?? i)} className="border-b last:border-0">
                          <td className="px-3 py-2 font-medium">{clean(ord.symbol)}</td>
                          <td className={cn("px-3 py-2", side === "BUY" ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>{side}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{clean(ord.qty)}</td>
                          <td className="px-3 py-2">{clean(ord.order_type)}</td>
                          <td className="px-3 py-2">{clean(ord.status)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
      </div>

      <PaperAutoTradePanel halted={halted} onAfterExecute={() => refresh(false)} />
    </div>
  );
}
