import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Eye, Zap, AlertTriangle } from "lucide-react";
import { api, type PaperTickState, type PaperTickOrder } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

function side(code: string) {
  return code === "buy" ? "text-emerald-600 dark:text-emerald-400" : "text-red-500";
}
function amount(o: PaperTickOrder): string {
  if (o.notional != null) return `$${o.notional.toLocaleString("en-US")}`;
  if (o.quantity != null) return `${o.quantity} 股`;
  return "—";
}

export function PaperAutoTradePanel({ halted, onAfterExecute }: { halted: boolean; onAfterExecute?: () => void }) {
  const [tick, setTick] = useState<PaperTickState | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const wasRunning = useRef(false);

  const poll = useCallback(async () => {
    try {
      const s = await api.getPaperTick();
      setTick(s);
      // When an execute run finishes, refresh the account/positions above.
      if (wasRunning.current && s.status !== "running") {
        wasRunning.current = false;
        if (s.dry_run === false) onAfterExecute?.();
      }
      if (s.status === "running") wasRunning.current = true;
    } catch { /* keep last state */ }
  }, [onAfterExecute]);

  useEffect(() => {
    poll();
    timer.current = setInterval(() => {
      // only poll while a run is active to avoid needless traffic
      if (wasRunning.current) poll();
    }, POLL_MS);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [poll]);

  const start = async (dryRun: boolean) => {
    if (!dryRun) {
      if (halted) { window.alert("Kill switch 已触发,先点上方「恢复」才能执行。"); return; }
      if (!window.confirm("执行一次:按稳健信号真实下 paper 单(模拟盘,无真钱)。确定?")) return;
    }
    setBusy(true);
    try {
      const s = await api.runPaperTick(dryRun);
      wasRunning.current = true;
      setTick(s);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "启动失败");
    } finally {
      setBusy(false);
    }
  };

  const running = tick?.status === "running";
  const r = tick?.result;

  return (
    <div className="app-panel space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="app-panel-title">自动交易 · 跟随稳健信号</h2>
          <p className="text-[11px] text-muted-foreground">
            按走势预测稳健策略把账户对齐到目标持仓 · 每日≤5笔 · 单笔≤$10k · 仅美股 · 手动触发
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => start(true)}
            disabled={busy || running}
            className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition hover:border-foreground/30 disabled:opacity-50"
          >
            {running && tick?.dry_run ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
            预览(dry-run)
          </button>
          <button
            onClick={() => start(false)}
            disabled={busy || running}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
          >
            {running && tick?.dry_run === false ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
            执行一次
          </button>
        </div>
      </div>

      {running && (
        <div className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {tick?.dry_run === false ? "执行中" : "预览计算中"}…每只美股要跑一遍稳健回测,约 1–2 分钟,请稍候。
        </div>
      )}

      {tick?.status === "error" && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400">
          运行失败:{tick.error}
        </div>
      )}

      {r && tick?.status === "done" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span>{r.dry_run ? "预览(未下单)" : "已执行"}</span>
            <span>今日已用 <span className="font-semibold text-foreground tabular-nums">{r.daily_count_after}/{r.limit_max_trades_per_day}</span> 笔</span>
            {r.halted && <span className="inline-flex items-center gap-1 text-red-500"><AlertTriangle className="h-3 w-3" />kill switch 已触发,执行会被拦截</span>}
            <span>{r.as_of}</span>
          </div>

          {/* Planned (dry-run) or the resulting orders */}
          {r.dry_run ? (
            <PlanTable title={`计划下单 (${r.planned.length})`} rows={r.planned} />
          ) : (
            <ExecTable rows={r.executed} />
          )}

          {r.skipped.length > 0 && (
            <details className="text-[11px] text-muted-foreground">
              <summary className="cursor-pointer">跳过 {r.skipped.length} 项</summary>
              <ul className="mt-1 space-y-0.5">
                {r.skipped.map((s, i) => (
                  <li key={`${s.code}-${i}`}><span className="font-mono">{s.code}</span> · {s.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function PlanTable({ title, rows }: { title: string; rows: PaperTickOrder[] }) {
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">无需调整——账户已对齐目标持仓。</p>;
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      <div className="app-table-shell">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">标的</th>
              <th className="px-3 py-2 text-left font-medium">方向</th>
              <th className="px-3 py-2 text-left font-medium">原因</th>
              <th className="px-3 py-2 text-right font-medium">规模</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o, i) => (
              <tr key={`${o.code}-${i}`} className="border-b last:border-0">
                <td className="px-3 py-2 font-medium">{o.code}</td>
                <td className={cn("px-3 py-2", side(o.side))}>{o.side === "buy" ? "买入" : "卖出"}</td>
                <td className="px-3 py-2 text-muted-foreground">{o.reason === "entry" ? "开仓" : "平仓"}</td>
                <td className="px-3 py-2 text-right tabular-nums">{amount(o)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ExecTable({ rows }: { rows: import("@/lib/api").PaperTickExecuted[] }) {
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">未下任何单(账户已对齐,或被 kill switch 拦截)。</p>;
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold">执行结果 ({rows.length})</h3>
      <div className="app-table-shell">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">标的</th>
              <th className="px-3 py-2 text-left font-medium">方向</th>
              <th className="px-3 py-2 text-right font-medium">规模</th>
              <th className="px-3 py-2 text-left font-medium">结果</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o, i) => (
              <tr key={`${o.code}-${i}`} className="border-b last:border-0">
                <td className="px-3 py-2 font-medium">{o.code}</td>
                <td className={cn("px-3 py-2", side(o.side))}>{o.side === "buy" ? "买入" : "卖出"}</td>
                <td className="px-3 py-2 text-right tabular-nums">{amount(o)}</td>
                <td className={cn("px-3 py-2", o.ok ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                  {o.ok ? (o.order_status ? o.order_status.split(".").pop() : "OK") : `失败:${o.error || "未知"}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
