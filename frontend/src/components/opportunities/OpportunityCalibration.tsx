import { useState } from "react";
import { AlertCircle, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { api, type OpportunityCalibrationSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

type Scope = "top3" | "all";

export function OpportunityCalibration() {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<Scope>("top3");
  const [data, setData] = useState<OpportunityCalibrationSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (nextScope: Scope) => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getOpportunityCalibration(nextScope));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "机会质量加载失败");
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && (!data || data.scope !== scope)) void load(scope);
  };

  const changeScope = (nextScope: Scope) => {
    if (nextScope === scope) return;
    setScope(nextScope);
    void load(nextScope);
  };

  return (
    <div className="border-t pt-3">
      <button type="button" onClick={toggle} className="flex w-full items-center justify-between py-1 text-left"
        aria-label={open ? "收起机会质量" : "展开机会质量"}>
        <span>
          <span className="block text-sm font-semibold text-foreground">机会质量</span>
          <span className="block text-[11px] text-muted-foreground">验证历史机会是否赚钱并跑赢市场</span>
        </span>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>

      {open && <div className="mt-3 space-y-3">
        <div className="inline-flex rounded-lg border p-0.5" aria-label="校准范围">
          {(["top3", "all"] as const).map((value) => <button key={value} type="button" onClick={() => changeScope(value)}
            className={cn("h-7 rounded-md px-3 text-xs", scope === value ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}>
            {value === "top3" ? "前三名" : "全部机会"}
          </button>)}
        </div>
        {data?.contains_fixed_universe_backfill && <p className="text-[11px] text-amber-600">{data.methodology_note}</p>}
        {loading ? <div className="flex h-24 items-center justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
          : error ? <div className="flex items-center gap-2 text-xs text-red-600"><AlertCircle className="h-4 w-4" />{error}</div>
          : data ? <div className="divide-y rounded-lg border px-3">
            {data.periods.map((period) => <div key={period.horizon_days} data-testid={`calibration-period-${period.horizon_days}`} className="grid grid-cols-2 gap-2 py-3 sm:grid-cols-[70px_repeat(5,minmax(0,1fr))] sm:items-center">
              <div className="col-span-2 sm:col-span-1"><p className="text-sm font-semibold">{period.horizon_days} 日</p><p className="text-[11px] text-muted-foreground">{period.completed_samples > 0 ? `${period.completed_samples} 个样本` : "样本积累中"}</p></div>
              <Metric label="胜率" value={formatPercent(period.win_rate)} />
              <Metric label="跑赢率" value={formatPercent(period.outperformance_rate)} />
              <Metric label="平均收益" value={formatPercent(period.average_return)} />
              <Metric label="平均超额" value={formatPercent(period.average_excess_return)} />
              <Metric label="最大亏损" value={formatPercent(period.max_loss)} danger />
            </div>)}
          </div> : null}
        <p className="text-[11px] text-muted-foreground">信号后下一交易日开盘买入；港股对比恒生指数，美股对比标普 500。</p>
      </div>}
    </div>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return <div><p className="text-[10px] text-muted-foreground">{label}</p><p className={cn("text-xs font-medium tabular-nums", danger && value !== "—" && "text-red-600")}>{value}</p></div>;
}

function formatPercent(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}
