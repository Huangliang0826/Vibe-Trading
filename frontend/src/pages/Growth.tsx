import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarCheck, ClipboardList, Flag, Pause, Pencil, Sprout, Target, Trash2, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  BLOCKERS,
  MAX_MAINTAIN,
  admissionBlock,
  buildWeeklyReview,
  countRole,
  loadGrowth,
  missedTwoDays,
  newId,
  saveGrowth,
  validateGoal,
  ymd,
  type Blocker,
  type DailyLog,
  type Goal,
  type GoalDraft,
  type GoalRole,
  type GrowthData,
  type PracticeKind,
} from "@/lib/growth/store";

const ROLE_META: Record<GoalRole, { label: string; className: string }> = {
  main: { label: "主攻", className: "bg-primary/10 text-primary" },
  maintain: { label: "维持", className: "bg-info/10 text-info" },
  paused: { label: "暂停", className: "bg-muted text-muted-foreground" },
};

const inputCls =
  "w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20";
const btnPrimary =
  "inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-60";
const btnGhost = "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground";

function useGrowth() {
  const [data, setData] = useState<GrowthData>(() => loadGrowth());
  const update = useCallback((fn: (d: GrowthData) => GrowthData) => {
    setData((prev) => {
      const next = fn(prev);
      if (next !== prev) saveGrowth(next);
      return next;
    });
  }, []);
  return { data, update };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

// ── 目标引擎 + 聚焦管理器 ─────────────────────────────────────────────────────
function emptyDraft(role: GoalRole): GoalDraft {
  return {
    domain: "",
    outcome: "",
    measure: "",
    deadline: "",
    role,
    dose: "",
    estimateHours: null,
    milestones: ["", "", ""],
    weeklyMinutes: 0,
    intention: "",
    minVersion: "",
  };
}

function GoalForm({
  goals,
  initial,
  editingId,
  today,
  onSave,
  onCancel,
}: {
  goals: Goal[];
  initial: GoalDraft;
  editingId?: string;
  today: string;
  onSave: (d: GoalDraft) => void;
  onCancel: () => void;
}) {
  const [d, setD] = useState<GoalDraft>(initial);
  const [errors, setErrors] = useState<string[]>([]);
  const set = <K extends keyof GoalDraft>(k: K, v: GoalDraft[K]) => setD((p) => ({ ...p, [k]: v }));
  const block = admissionBlock(goals, d.role, editingId);

  const submit = () => {
    const errs = validateGoal(d, today);
    if (block) errs.unshift(block);
    setErrors(errs);
    if (errs.length === 0) onSave(d);
  };

  return (
    <div className="space-y-4 rounded-2xl border bg-card p-5">
      <p className="text-sm font-medium">{editingId ? "编辑目标" : "新目标"}:做到时是什么样子?怎么测?什么时候?</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="领域">
          <input className={inputCls} value={d.domain} onChange={(e) => set("domain", e.target.value)} placeholder="荷兰语 / 健身 / 睡眠" />
        </Field>
        <Field label="角色" hint={`主攻最多 1 个,维持最多 ${MAX_MAINTAIN} 个`}>
          <select className={inputCls} value={d.role} onChange={(e) => set("role", e.target.value as GoalRole)}>
            <option value="main">主攻</option>
            <option value="maintain">维持</option>
            <option value="paused">暂停</option>
          </select>
        </Field>
      </div>
      <Field label="可观察的结果">
        <input className={inputCls} value={d.outcome} onChange={(e) => set("outcome", e.target.value)} placeholder="能用荷兰语和陌生人连续交谈 15 分钟" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="测量方法">
          <input className={inputCls} value={d.measure} onChange={(e) => set("measure", e.target.value)} placeholder="以录音为证" />
        </Field>
        <Field label="截止日期">
          <input type="date" className={inputCls} value={d.deadline} min={today} onChange={(e) => set("deadline", e.target.value)} />
        </Field>
      </div>
      {d.role === "maintain" && (
        <Field label="维持剂量" hint="只求不退步,系统不提示进步不足">
          <input className={inputCls} value={d.dose} onChange={(e) => set("dose", e.target.value)} placeholder="每天 15 分钟阅读 / 每周 2 次训练" />
        </Field>
      )}
      {d.role !== "maintain" && (
        <>
          <div className="space-y-2">
            <span className="text-xs font-medium">三个月度里程碑</span>
            {d.milestones.map((m, i) => (
              <input
                key={i}
                className={inputCls}
                value={m}
                onChange={(e) => set("milestones", d.milestones.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder={`第 ${i + 1} 个月`}
              />
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="每周投入(分钟)" hint="写投入量,不写结果——投入是自己能控制的">
              <input
                type="number"
                min={0}
                className={inputCls}
                value={d.weeklyMinutes || ""}
                onChange={(e) => set("weeklyMinutes", Number(e.target.value) || 0)}
                placeholder="180"
              />
            </Field>
            <Field label="所需投入估算(小时,可选)" hint="用于进度预测">
              <input
                type="number"
                min={0}
                className={inputCls}
                value={d.estimateHours ?? ""}
                onChange={(e) => set("estimateHours", e.target.value ? Number(e.target.value) : null)}
                placeholder="600"
              />
            </Field>
          </div>
          <Field label="执行意图" hint="在什么时间、什么地点、做完什么之后,我就做什么">
            <input className={inputCls} value={d.intention} onChange={(e) => set("intention", e.target.value)} placeholder="每天早餐后,在书桌前,上 30 分钟荷兰语课" />
          </Field>
          <Field label="2 分钟最小版本" hint="状态差的日子只做这个,保住节奏">
            <input className={inputCls} value={d.minVersion} onChange={(e) => set("minVersion", e.target.value)} placeholder="听 2 分钟荷兰语播客" />
          </Field>
        </>
      )}
      {errors.length > 0 && (
        <ul className="space-y-1 rounded-lg bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          {errors.map((e) => (
            <li key={e}>· {e}</li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <button type="button" className={btnPrimary} onClick={submit}>
          保存目标
        </button>
        <button type="button" className="rounded-xl px-4 py-2 text-sm text-muted-foreground hover:text-foreground" onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}

function GoalsPanel({ data, update, today }: { data: GrowthData; update: (fn: (d: GrowthData) => GrowthData) => void; today: string }) {
  const [editing, setEditing] = useState<{ id?: string; draft: GoalDraft } | null>(null);
  const sorted = useMemo(() => {
    const order: Record<GoalRole, number> = { main: 0, maintain: 1, paused: 2 };
    return [...data.goals].sort((a, b) => order[a.role] - order[b.role]);
  }, [data.goals]);

  const save = (d: GoalDraft) => {
    update((prev) => {
      if (editing?.id) return { ...prev, goals: prev.goals.map((g) => (g.id === editing.id ? { ...g, ...d } : g)) };
      return { ...prev, goals: [...prev.goals, { ...d, id: newId("goal"), createdAt: today }] };
    });
    setEditing(null);
  };

  const setRole = (id: string, role: GoalRole) => update((prev) => ({ ...prev, goals: prev.goals.map((g) => (g.id === id ? { ...g, role } : g)) }));
  const remove = (id: string) => {
    if (!window.confirm("删除这个目标及其签到记录?")) return;
    update((prev) => ({ goals: prev.goals.filter((g) => g.id !== id), logs: prev.logs.filter((l) => l.goalId !== id), version: 1 }));
  };

  const nextRole: GoalRole = countRole(data.goals, "main") === 0 ? "main" : "maintain";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>聚焦:</span>
        <span className={cn("rounded-full px-2 py-0.5", ROLE_META.main.className)}>主攻 {countRole(data.goals, "main")}/1</span>
        <span className={cn("rounded-full px-2 py-0.5", ROLE_META.maintain.className)}>
          维持 {countRole(data.goals, "maintain")}/{MAX_MAINTAIN}
        </span>
        <span className={cn("rounded-full px-2 py-0.5", ROLE_META.paused.className)}>暂停 {countRole(data.goals, "paused")}</span>
      </div>

      {editing ? (
        <GoalForm
          key={editing.id ?? "new"}
          goals={data.goals}
          initial={editing.draft}
          editingId={editing.id}
          today={today}
          onSave={save}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <button type="button" className={btnPrimary} onClick={() => setEditing({ draft: emptyDraft(nextRole) })}>
          <Target className="h-4 w-4" /> 新建目标
        </button>
      )}

      {sorted.length === 0 && !editing && (
        <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          还没有目标。先把一个愿望写成可检验的目标:可观察的结果 + 测量方法 + 截止日期。
        </p>
      )}

      {sorted.map((g) => (
        <div key={g.id} className={cn("space-y-2 rounded-2xl border bg-card p-4", g.role === "paused" && "opacity-70")}>
          <div className="flex items-start gap-2">
            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", ROLE_META[g.role].className)}>{ROLE_META[g.role].label}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {g.domain}:{g.outcome}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                测量:{g.measure} · 截止 {g.deadline}
              </p>
            </div>
            <div className="flex shrink-0 gap-1">
              <button type="button" className={btnGhost} onClick={() => setEditing({ id: g.id, draft: { ...g } })} aria-label="编辑">
                <Pencil className="h-3.5 w-3.5" />
              </button>
              {g.role !== "paused" && (
                <button type="button" className={btnGhost} onClick={() => setRole(g.id, "paused")} aria-label="暂停">
                  <Pause className="h-3.5 w-3.5" />
                </button>
              )}
              <button type="button" className={btnGhost} onClick={() => remove(g.id)} aria-label="删除">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          {g.role === "maintain" && <p className="text-xs">最低剂量:{g.dose}</p>}
          {g.role !== "maintain" && (
            <div className="space-y-1 text-xs">
              <p>
                每周投入 <b>{g.weeklyMinutes}</b> 分钟 · {g.intention}
              </p>
              {g.minVersion && <p className="text-muted-foreground">最小版本:{g.minVersion}</p>}
              {g.milestones.some((m) => m.trim()) && (
                <ol className="list-inside list-decimal text-muted-foreground">
                  {g.milestones.filter((m) => m.trim()).map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ol>
              )}
            </div>
          )}
          {g.role === "paused" && (
            <div className="flex gap-2">
              {(["main", "maintain"] as const).map((r) => {
                const blocked = admissionBlock(data.goals, r, g.id);
                return (
                  <button
                    key={r}
                    type="button"
                    className={cn(btnGhost, "border")}
                    disabled={Boolean(blocked)}
                    title={blocked ?? undefined}
                    onClick={() => setRole(g.id, r)}
                  >
                    恢复为{ROLE_META[r].label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── 晚间签到 ─────────────────────────────────────────────────────────────────
function CheckInPanel({ data, update, today }: { data: GrowthData; update: (fn: (d: GrowthData) => GrowthData) => void; today: string }) {
  const main = data.goals.find((g) => g.role === "main");
  const hasMaintain = countRole(data.goals, "maintain") > 0;
  const existing = main ? data.logs.find((l) => l.goalId === main.id && l.date === today) : undefined;

  const [minutes, setMinutes] = useState(existing?.minutes ?? 30);
  const [kind, setKind] = useState<PracticeKind>(existing?.kind ?? "output");
  const [difficulty, setDifficulty] = useState(existing?.difficulty ?? 3);
  const [maintainDone, setMaintainDone] = useState<boolean | null>(existing?.maintainDone ?? (hasMaintain ? true : null));
  const [blocker, setBlocker] = useState<Blocker>(existing?.blocker ?? "没有");
  const [win, setWin] = useState(existing?.win ?? "");
  const [saved, setSaved] = useState(false);

  if (!main) return <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">先在「目标」里设一个主攻目标,再来签到。</p>;

  const chip = (active: boolean) =>
    cn("rounded-lg border px-3 py-1.5 text-xs transition", active ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted");

  const submit = () => {
    const log: DailyLog = { date: today, goalId: main.id, minutes, kind, difficulty, maintainDone: hasMaintain ? maintainDone : null, blocker, win };
    update((prev) => ({ ...prev, logs: [...prev.logs.filter((l) => !(l.goalId === main.id && l.date === today)), log] }));
    setSaved(true);
  };

  return (
    <div className="space-y-5 rounded-2xl border bg-card p-5">
      {missedTwoDays(data.logs, today) && (
        <p className="rounded-lg bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          已经两天没签到了。没关系,今天哪怕只做最小版本也算数{main.minVersion ? `:${main.minVersion}` : ""}。
        </p>
      )}
      <div className="space-y-2">
        <p className="text-sm font-medium">1. 今天在「{main.domain}」上做了什么?投入多少分钟?</p>
        <div className="flex flex-wrap gap-2">
          {[0, 2, 15, 30, 45, 60, 90].map((m) => (
            <button key={m} type="button" className={chip(minutes === m)} onClick={() => setMinutes(m)}>
              {m} 分钟
            </button>
          ))}
          <input type="number" min={0} className={cn(inputCls, "w-24 py-1.5 text-xs")} value={minutes} onChange={(e) => setMinutes(Math.max(0, Number(e.target.value) || 0))} />
        </div>
        <div className="flex gap-2">
          {(["input", "output"] as const).map((k) => (
            <button key={k} type="button" className={chip(kind === k)} onClick={() => setKind(k)}>
              {k === "input" ? "输入(听、读)" : "输出(说、写、训练)"}
            </button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">2. 难度几分?(1 很轻松,5 很吃力;理想 3~4)</p>
        <div className="flex gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" className={chip(difficulty === n)} onClick={() => setDifficulty(n)}>
              {n}
            </button>
          ))}
        </div>
      </div>
      {hasMaintain && (
        <div className="space-y-2">
          <p className="text-sm font-medium">3. 维持目标完成了最低剂量吗?</p>
          <div className="flex gap-2">
            <button type="button" className={chip(maintainDone === true)} onClick={() => setMaintainDone(true)}>
              是
            </button>
            <button type="button" className={chip(maintainDone === false)} onClick={() => setMaintainDone(false)}>
              否
            </button>
          </div>
        </div>
      )}
      <div className="space-y-2">
        <p className="text-sm font-medium">{hasMaintain ? 4 : 3}. 今天最大的拦路虎是什么?</p>
        <div className="flex flex-wrap gap-2">
          {BLOCKERS.map((b) => (
            <button key={b} type="button" className={chip(blocker === b)} onClick={() => setBlocker(b)}>
              {b}
            </button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">{hasMaintain ? 5 : 4}. 今天做到的一件事是什么?</p>
        <input className={inputCls} value={win} onChange={(e) => setWin(e.target.value)} placeholder="不论大小" />
      </div>
      <div className="flex items-center gap-3">
        <button type="button" className={btnPrimary} onClick={submit}>
          <CalendarCheck className="h-4 w-4" /> {existing ? "更新今日签到" : "完成签到"}
        </button>
        {saved && <span className="text-xs text-primary">已记录。明天见 👋</span>}
      </div>
    </div>
  );
}

// ── 每周复盘 ─────────────────────────────────────────────────────────────────
function ReviewPanel({ data, today }: { data: GrowthData; today: string }) {
  const r = useMemo(() => buildWeeklyReview(data, today), [data, today]);
  if (!r) return <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">设定主攻目标并签到一周后,这里会生成复盘报告。</p>;

  const delta = r.completion !== null && r.prevCompletion !== null ? r.completion - r.prevCompletion : null;
  const rows: { icon: typeof Flag; title: string; body: React.ReactNode }[] = [
    {
      icon: TrendingUp,
      title: "本周投入",
      body:
        r.completion === null ? (
          `${r.doneMinutes} 分钟`
        ) : (
          <>
            {r.doneMinutes}/{r.plannedMinutes} 分钟,完成 <b>{r.completion}%</b>
            {delta !== null && <span className="text-muted-foreground">(较上周 {delta >= 0 ? `+${delta}` : delta} 个百分点)</span>}
          </>
        ),
    },
    {
      icon: Flag,
      title: "头号拦路虎",
      body: r.topBlocker ? `「${r.topBlocker.blocker}」出现 ${r.topBlocker.count} 次` : "本周没有记录到拦路虎",
    },
    {
      icon: CalendarCheck,
      title: "进度预测",
      body: r.forecast ? (
        <>
          按当前速度预计 <b>{r.forecast.date}</b> 达成
          {r.forecast.late && <span className="text-amber-600 dark:text-amber-400">,晚于截止日期:要么增加投入,要么延后截止,要么缩小目标</span>}
        </>
      ) : (
        "填写「所需投入估算」并持续签到后可预测"
      ),
    },
    { icon: Target, title: "唯一调整", body: r.adjustment },
    { icon: Sprout, title: "本周亮点", body: r.highlight ?? "本周还没有记录收获" },
  ];

  return (
    <div className="space-y-3 rounded-2xl border bg-card p-5">
      <p className="text-xs text-muted-foreground">
        {r.weekStart} ~ {r.weekEnd} · 签到 {r.loggedDays}/7 天
      </p>
      {rows.map(({ icon: Icon, title, body }, i) => (
        <div key={title} className="flex gap-3">
          <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
            <Icon className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 text-sm">
            <p className="text-xs font-medium text-muted-foreground">
              {i + 1}. {title}
            </p>
            <p className="mt-0.5">{body}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── 页面 ───────────────────────────────────────────────────────────────────
type Tab = "goals" | "checkin" | "review";
const TABS = [
  { key: "goals", label: "目标", icon: Target },
  { key: "checkin", label: "晚间签到", icon: CalendarCheck },
  { key: "review", label: "每周复盘", icon: ClipboardList },
] as const;

export function Growth() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("tab");
  const tab: Tab = raw === "checkin" || raw === "review" ? raw : "goals";
  const { data, update } = useGrowth();
  const today = ymd(new Date());

  const selectTab = (t: Tab) => {
    const next = new URLSearchParams(searchParams);
    if (t === "goals") next.delete("tab");
    else next.set("tab", t);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-7 sm:px-6 sm:py-9">
      <div className="flex items-start gap-4">
        <div className="mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/10">
          <Sprout className="h-5 w-5" strokeWidth={1.8} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="page-kicker">Personal growth</p>
          <h1 className="mt-1.5 text-[30px] font-semibold leading-tight tracking-[-0.035em] sm:text-[32px]">个人成长</h1>
          <p className="mt-2 text-sm text-muted-foreground">明确目标 → 有效行动 → 获得反馈 → 调整方法,让循环每天转起来</p>
        </div>
      </div>

      <div role="tablist" aria-label="成长栏目" className="inline-flex rounded-lg border bg-muted/30 p-1">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => selectTab(key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-colors",
              tab === key ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "goals" && <GoalsPanel data={data} update={update} today={today} />}
      {tab === "checkin" && <CheckInPanel key={today} data={data} update={update} today={today} />}
      {tab === "review" && <ReviewPanel data={data} today={today} />}
    </div>
  );
}
