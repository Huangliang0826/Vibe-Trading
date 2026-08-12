import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Eye, Zap, AlertTriangle, Clock, History } from "lucide-react";
import { api, type PaperTickState, type PaperTickOrder, type PaperScheduleState, type PaperAction } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

function side(code: string) {
  return code === "buy" ? "text-emerald-600 dark:text-emerald-400" : "text-red-500";
}
// The ledger records the status at submit time; a market order almost always
// fills seconds later, so raw PENDING_NEW/NEW reads as "stuck" when it isn't.
function statusLabel(raw: string | null): string {
  const s = (raw || "").split(".").pop() || "";
  if (s === "PENDING_NEW" || s === "NEW" || s === "ACCEPTED") return "已提交";
  if (s === "FILLED") return "已成交";
  if (s === "PARTIALLY_FILLED") return "部分成交";
  if (s === "CANCELED" || s === "CANCELLED") return "已撤销";
  return s || "OK";
}

function amount(o: { notional: number | null; quantity: number | null }): string {
  if (o.notional != null) return `$${o.notional.toLocaleString("en-US")}`;
  if (o.quantity != null) return `${o.quantity} 股`;
  return "—";
}

export function PaperAutoTradePanel({ halted, onAfterExecute }: { halted: boolean; onAfterExecute?: () => void }) {
  const [tick, setTick] = useState<PaperTickState | null>(null);
  const [busy, setBusy] = useState(false);
  const [schedule, setSchedule] = useState<PaperScheduleState | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [actions, setActions] = useState<PaperAction[] | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const wasRunning = useRef(false);

  const refreshActions = useCallback(() => {
    api.getPaperActions(50).then((r) => setActions(r.actions)).catch(() => {});
  }, []);

  const poll = useCallback(async () => {
    try {
      const s = await api.getPaperTick();
      setTick(s);
      // When an execute run finishes, refresh the account/positions + audit log.
      if (wasRunning.current && s.status !== "running") {
        wasRunning.current = false;
        refreshActions();
        if (s.dry_run === false) onAfterExecute?.();
      }
      if (s.status === "running") wasRunning.current = true;
    } catch { /* keep last state */ }
  }, [onAfterExecute, refreshActions]);

  useEffect(() => {
    poll();
    refreshActions();
    api.getPaperSchedule().then(setSchedule).catch(() => {});
    timer.current = setInterval(() => {
      // only poll while a run is active to avoid needless traffic
      if (wasRunning.current) poll();
    }, POLL_MS);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [poll, refreshActions]);

  const toggleSchedule = async () => {
    const next = !schedule?.enabled;
    if (next && !window.confirm(
      "开启每日自动执行:每个美股交易日开盘后(10:00 ET)自动按稳健信号下 paper 单。\n" +
      "注意:kill switch 仍是总闸——它开着时定时任务会空转不下单。确定开启?",
    )) return;
    setScheduleBusy(true);
    try {
      setSchedule(await api.setPaperSchedule(next));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "操作失败");
    } finally {
      setScheduleBusy(false);
    }
  };

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

      {/* Daily scheduler toggle (Phase 2c) */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/20 px-3 py-2.5">
        <div className="flex items-center gap-2 text-xs">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="font-medium">每日自动执行</span>
          <span className="text-muted-foreground">
            开盘后 {schedule?.run_after_et ?? "10:00"} ET · 上次 {schedule?.last_run_date ?? "—"}
          </span>
        </div>
        <button
          onClick={toggleSchedule}
          disabled={scheduleBusy || !schedule}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-medium transition disabled:opacity-50",
            schedule?.enabled ? "bg-emerald-600 text-white hover:opacity-90" : "border hover:border-foreground/30",
          )}
        >
          {scheduleBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {schedule?.enabled ? "已开启 · 点击关闭" : "已关闭 · 点击开启"}
        </button>
      </div>
      {schedule?.enabled && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-400">
          自动执行已开启。真正下单还需 kill switch 处于「恢复」状态——它触发时定时任务只空转、不下单。
        </div>
      )}

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

      {/* Audit log — every executed order the auto-trader placed */}
      {actions && actions.length > 0 && (
        <div className="border-t pt-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold">
            <History className="h-4 w-4 text-muted-foreground" />操作日志 ({actions.length})
          </div>
          <div className="app-table-shell max-h-72 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">时间</th>
                  <th className="px-3 py-2 text-left font-medium">标的</th>
                  <th className="px-3 py-2 text-left font-medium">方向</th>
                  <th className="px-3 py-2 text-right font-medium">规模</th>
                  <th className="px-3 py-2 text-left font-medium">结果</th>
                </tr>
              </thead>
              <tbody>
                {actions.map((a, i) => (
                  <tr key={`${a.as_of}-${a.code}-${i}`} className="border-b last:border-0">
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">{a.as_of.replace("T", " ").replace("Z", "")}</td>
                    <td className="px-3 py-2 font-medium">{a.code}</td>
                    <td className={cn("px-3 py-2", side(a.side))}>{a.side === "buy" ? "买入" : "卖出"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{amount(a)}</td>
                    <td className={cn("px-3 py-2", a.ok ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
                      {a.ok ? statusLabel(a.order_status) : `失败:${a.error || "未知"}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
                  {o.ok ? statusLabel(o.order_status) : `失败:${o.error || "未知"}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
