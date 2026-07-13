interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  delta?: number | null;
  sparkline?: number[];
}

function sparklinePoints(values: number[]): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = 28 - ((value - min) / span) * 24;
    return `${x},${y}`;
  }).join(" ");
}

export function MetricCard({ label, value, detail, delta, sparkline = [] }: MetricCardProps) {
  return (
    <article className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        </div>
        {delta != null && Number.isFinite(delta) && (
          <span className={delta >= 0 ? "text-xs text-emerald-500" : "text-xs text-red-500"}>
            {delta >= 0 ? "+" : ""}{delta.toFixed(1)}%
          </span>
        )}
      </div>
      {sparkline.length > 1 && (
        <svg viewBox="0 0 100 32" className="mt-3 h-8 w-full" role="img" aria-label={`${label}趋势`}>
          <polyline points={sparklinePoints(sparkline)} fill="none" stroke="currentColor" strokeWidth="2" className="text-primary" />
        </svg>
      )}
      {detail && <p className="mt-2 text-[11px] text-muted-foreground">{detail}</p>}
    </article>
  );
}
