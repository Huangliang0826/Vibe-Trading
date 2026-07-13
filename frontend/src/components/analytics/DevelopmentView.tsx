import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, GitCommitHorizontal, PackageOpen } from "lucide-react";
import { api, type AnalyticsDays, type AnalyticsDevelopmentResponse } from "@/lib/api";

export function DevelopmentView({ days }: { days: AnalyticsDays }) {
  const [data, setData] = useState<AnalyticsDevelopmentResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [windowDays, setWindowDays] = useState<7 | 30>(7);
  const [release, setRelease] = useState<string | undefined>();

  useEffect(() => {
    let cancelled = false;
    api.getAnalyticsDevelopment(days, release, windowDays).then((response) => {
      if (!cancelled) setData(response);
    }).catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [days, release, windowDays]);

  if (!data) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const totals = data.commits.reduce((sum, commit) => ({ files: sum.files + commit.files_changed, insertions: sum.insertions + commit.insertions, deletions: sum.deletions + commit.deletions }), { files: 0, insertions: 0, deletions: 0 });

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[['Commits', data.commits.length], ['Files', totals.files], ['Insertions', `+${totals.insertions}`], ['Deletions', `−${totals.deletions}`]].map(([label, value]) => <div key={label} className="rounded-xl border bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-[10px] text-muted-foreground">变更规模</p></div>)}
      </div>

      <section className="rounded-xl border bg-card p-4"><h2 className="flex items-center gap-2 text-sm font-semibold"><GitCommitHorizontal className="h-4 w-4" />最近功能变化</h2><div className="mt-3 space-y-2">{data.feature_groups.map((group) => <div key={`${group.ended_at}-${group.label}`} className="rounded-lg border p-3"><button className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setExpanded(expanded === group.label ? null : group.label)}><div><p className="font-medium">{group.label}</p><p className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground"><span>{group.modules.join(" · ")}</span><span>{group.files_changed} files</span><span>+{group.insertions}</span><span>−{group.deletions}</span></p></div>{expanded === group.label ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button><p className="mt-2 font-mono text-[11px] text-muted-foreground">{group.commit_shas.map((sha) => sha.slice(0, 7)).join(" · ")}</p>{expanded === group.label && <ul className="mt-2 space-y-1 text-xs text-muted-foreground">{group.subjects.map((subject) => <li key={subject}>{subject}</li>)}</ul>}</div>)}</div></section>

      <section className="rounded-xl border bg-card p-4"><h2 className="text-sm font-semibold">模块代码变化趋势</h2><div className="mt-3 space-y-2">{data.module_churn.map((row) => <div key={row.module}><div className="flex justify-between text-xs"><span>{row.module}</span><span>{row.changed_lines.toLocaleString()} 行</span></div><div className="mt-1 h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${Math.max(4, Math.min(100, row.changed_lines / Math.max(1, data.module_churn[0]?.changed_lines) * 100))}%` }} /></div></div>)}</div></section>

      <section className="rounded-xl border bg-card p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-sm font-semibold"><PackageOpen className="h-4 w-4" />版本窗口</h2><div className="flex gap-2"><select aria-label="版本" value={release || ""} onChange={(event) => setRelease(event.target.value || undefined)} className="rounded border bg-background px-2 py-1 text-xs"><option value="">选择版本</option>{data.releases.map((item) => <option key={item.tag}>{item.tag}</option>)}</select><select aria-label="对比窗口" value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value) as 7 | 30)} className="rounded border bg-background px-2 py-1 text-xs"><option value={7}>7 天</option><option value={30}>30 天</option></select></div></div>{data.release_comparison && <div className="mt-3"><p className="text-sm">{data.release_comparison.status === "insufficient_sample" ? "样本不足" : data.release_comparison.tag}</p><p className="mt-1 text-xs text-muted-foreground">{data.release_comparison.disclaimer}</p></div>}</section>
    </section>
  );
}
