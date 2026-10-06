/** 个人成长:睡眠 / 健身 / 荷兰语 / 英语 的两周计划与每日打卡。
 *
 *  设计出发点是一句用户原话:"我不想自己去设置复杂的计划"。所以:
 *
 *  * 建计划只有点选,没有一个必填的输入框——其余由模型展开成 14 天具体动作。
 *  * 每天的反馈压到一次点击。点完立刻给回应(连续天数、进度格子前进一格),
 *    而不是存起来等以后某个报表。
 *  * 进步要能被指着说,所以每个领域都有检查点:第 1 天记一条基线,两周后再记
 *    一条,界面把两条并排摆出来。
 *
 *  状态全部存后端(见 agent/src/growth),手机打卡和电脑回顾是同一份数据。
 */
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  BookOpen, Check, Dumbbell, Flame, Languages, Loader2, Moon, RotateCcw,
  MessagesSquare, Sparkles, Sprout, Target, Undo2,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  api, type GrowthDomainProgress, type GrowthOptions, type GrowthState,
} from "@/lib/api";
import { EnglishDrill } from "@/pages/growth/EnglishDrill";
import { EnglishQuiz } from "@/pages/growth/EnglishQuiz";

const DOMAIN_ICONS: Record<string, typeof Moon> = {
  sleep: Moon,
  fitness: Dumbbell,
  dutch: Languages,
  english: BookOpen,
};

const FEELINGS = [
  { value: 1, label: "有点难" },
  { value: 2, label: "还行" },
  { value: 3, label: "不错" },
] as const;

const chip =
  "rounded-full border px-3 py-1.5 text-sm transition-colors hover:border-primary/50";
const chipOn = "border-primary bg-primary/10 font-medium text-primary";
const chipOff = "border-border text-muted-foreground";

/** 一行说明。页面标题交给侧栏——每个 tab 都顶一个大标题只是在挤走内容。 */
function Lede({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

// ── 建计划:全部点选 ─────────────────────────────────────────────────────────

interface Picks {
  on: boolean;
  level: string;
  minutes: number;
}

function Setup({ options, onCreated }: { options: GrowthOptions; onCreated: (s: GrowthState) => void }) {
  const [picks, setPicks] = useState<Record<string, Picks>>(() =>
    Object.fromEntries(
      options.domains.map((d) => [d.key, { on: true, level: d.levels[0].key, minutes: options.minutes[0] }]),
    ),
  );
  const [chronotype, setChronotype] = useState(options.chronotypes[0].key);
  const [busy, setBusy] = useState(false);

  const chosen = options.domains.filter((d) => picks[d.key]?.on);

  const submit = async () => {
    if (!chosen.length) return;
    setBusy(true);
    try {
      onCreated(await api.createGrowthPlan({
        chronotype,
        domains: Object.fromEntries(
          chosen.map((d) => [d.key, { level: picks[d.key].level, minutes: picks[d.key].minutes }]),
        ),
      }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "生成失败");
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Lede>选几下就好,剩下的交给 AI 排。两周后有一次检查点,能看出变化。</Lede>

      <div className="space-y-4">
        {options.domains.map((domain) => {
          const pick = picks[domain.key];
          const Icon = DOMAIN_ICONS[domain.key] ?? Sprout;
          const set = (patch: Partial<Picks>) =>
            setPicks((prev) => ({ ...prev, [domain.key]: { ...prev[domain.key], ...patch } }));

          return (
            <div
              key={domain.key}
              className={cn(
                "space-y-4 rounded-2xl border bg-card p-5 transition-opacity",
                !pick.on && "opacity-55",
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Icon className="h-[18px] w-[18px] text-primary" strokeWidth={1.8} />
                  <span className="text-[15px] font-medium">{domain.label}</span>
                </div>
                <button
                  type="button"
                  onClick={() => set({ on: !pick.on })}
                  className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                >
                  {pick.on ? "这次不做" : "加回来"}
                </button>
              </div>

              {pick.on && (
                <>
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">现在的状态</p>
                    <div className="flex flex-wrap gap-2">
                      {domain.levels.map((level) => (
                        <button
                          key={level.key}
                          type="button"
                          onClick={() => set({ level: level.key })}
                          className={cn(chip, pick.level === level.key ? chipOn : chipOff)}
                        >
                          {level.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">每天能给</p>
                    <div className="flex flex-wrap gap-2">
                      {options.minutes.map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => set({ minutes: m })}
                          className={cn(chip, pick.minutes === m ? chipOn : chipOff)}
                        >
                          {m} 分钟
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="space-y-2 rounded-2xl border bg-card p-5">
        <p className="text-xs text-muted-foreground">我的作息</p>
        <div className="flex flex-wrap gap-2">
          {options.chronotypes.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => setChronotype(c.key)}
              className={cn(chip, chronotype === c.key ? chipOn : chipOff)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={busy || !chosen.length}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3.5 text-[15px] font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50 sm:w-auto"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
        {busy ? "正在排计划…" : `生成 ${options.days} 天计划`}
      </button>
    </div>
  );
}

function Generating({ ready, total }: { ready: number; total: number }) {
  return (
    <div className="space-y-6">
      <Lede>正在为每个领域排 14 天的具体动作。</Lede>
      <div className="space-y-4 rounded-2xl border bg-card p-6">
        <div className="flex items-center gap-2.5 text-sm font-medium">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          已排好 {ready} / {total} 个领域
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${total ? (ready / total) * 100 : 0}%` }}
          />
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          一个领域要二三十秒,四个大约一两分钟。可以先去别的页面,排好了回来就在。
        </p>
      </div>
    </div>
  );
}

// ── 每天 ─────────────────────────────────────────────────────────────────────

function Dots({ dots }: { dots: GrowthDomainProgress["dots"] }) {
  return (
    <div className="flex flex-wrap gap-1" aria-hidden="true">
      {dots.map((kind, i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 w-[14px] rounded-full",
            kind === "done" && "bg-primary",
            kind === "next" && "bg-primary/40",
            kind === "todo" && "bg-muted-foreground/15",
          )}
        />
      ))}
    </div>
  );
}

function DomainCard({
  item,
  onCheckin,
  onUndo,
}: {
  item: GrowthDomainProgress;
  onCheckin: (domain: string, feeling?: number) => Promise<void>;
  onUndo: (domain: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const Icon = DOMAIN_ICONS[item.domain] ?? Sprout;
  // 打完卡后显示刚做完的那一步,而不是明天的内容——否则"今天完成"会贴在一个
  // 还没做的动作上。
  const step = item.done_today ? item.today_step : item.next_step;
  const finished = item.next_step === null && !item.done_today;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={cn(
        "space-y-4 rounded-2xl border bg-card p-5 transition-colors",
        item.done_today && "border-primary/35 bg-primary/[0.04]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Icon className="h-[18px] w-[18px] text-primary" strokeWidth={1.8} />
          <span className="text-[15px] font-medium">{item.label}</span>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">{item.done}</span> / {item.total} 天
        </span>
      </div>

      <Dots dots={item.dots} />

      {finished || !step ? (
        <p className="text-sm text-muted-foreground">这个领域两周的内容已经全部做完了。</p>
      ) : (
        <div className="space-y-1">
          <p className="text-[15px] font-medium">{step.title}</p>
          <p className="text-sm leading-relaxed text-muted-foreground">{step.detail}</p>
          <p className="text-xs text-muted-foreground/80">约 {step.minutes} 分钟</p>
        </div>
      )}

      {item.next_step !== null && !item.done_today && (
        <>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => onCheckin(item.domain))}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary transition hover:bg-primary/15 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            做完了
          </button>
          {item.min_version && (
            <p className="text-xs text-muted-foreground">
              状态不好?做这个也算:{item.min_version}
            </p>
          )}
        </>
      )}

      {item.done_today && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
              <Check className="h-4 w-4" />今天完成
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => onUndo(item.domain))}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-50"
            >
              <Undo2 className="h-3 w-3" />撤销
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">感觉如何?</span>
            {FEELINGS.map((f) => (
              <button
                key={f.value}
                type="button"
                disabled={busy}
                onClick={() => run(() => onCheckin(item.domain, f.value))}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs transition-colors disabled:opacity-50",
                  item.feeling_today === f.value ? chipOn : chipOff,
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CheckpointPanel({
  state,
  onSave,
}: {
  state: GrowthState;
  onSave: (domain: string, which: "start" | "end", value: string) => Promise<void>;
}) {
  const overview = state.overview!;
  const marks = state.checkpoints ?? {};
  const due = overview.checkpoint.due;

  return (
    <div className="space-y-4 rounded-2xl border bg-card p-5">
      <div>
        <h2 className="text-[15px] font-medium">两周检查点</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {due
            ? "到期了。再测一次,和第 1 天的记录放在一起看。"
            : `还有 ${overview.checkpoint.days_left} 天到期(${overview.checkpoint.due_date})。先把第 1 天的基线记下来,否则到时候没有对比的对象。`}
        </p>
      </div>

      <div className="space-y-4">
        {overview.domains.map((item) => {
          const mark = marks[item.domain] ?? {};
          const slot: "start" | "end" = mark.start ? "end" : "start";
          const both = Boolean(mark.start && mark.end);

          return (
            <div key={item.domain} className="space-y-2 border-t pt-4 first:border-t-0 first:pt-0">
              <p className="text-sm font-medium">{item.label}</p>
              <p className="text-xs leading-relaxed text-muted-foreground">{item.checkpoint}</p>

              {both ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="rounded-lg bg-muted/60 px-2.5 py-1 text-muted-foreground">
                    第 1 天 · {mark.start}
                  </span>
                  <span className="text-muted-foreground">→</span>
                  <span className="rounded-lg bg-primary/10 px-2.5 py-1 font-medium text-primary">
                    第 {overview.checkpoint.elapsed_days + 1} 天 · {mark.end}
                  </span>
                </div>
              ) : (
                <CheckpointInput
                  domain={item.domain}
                  slot={slot}
                  baseline={mark.start}
                  disabled={slot === "end" && !due}
                  onSave={onSave}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CheckpointInput({
  domain,
  slot,
  baseline,
  disabled,
  onSave,
}: {
  domain: string;
  slot: "start" | "end";
  baseline?: string;
  disabled: boolean;
  onSave: (domain: string, which: "start" | "end", value: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!value.trim()) return;
    setBusy(true);
    try {
      await onSave(domain, slot, value);
      setValue("");
    } finally {
      setBusy(false);
    }
  };

  if (disabled) {
    return (
      <p className="text-xs text-muted-foreground">
        基线已记:{baseline}。两周到期后再来记结果。
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()}
        placeholder={slot === "start" ? "现在测出来是多少?" : "两周后测出来是多少?"}
        className="min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:border-primary/60"
      />
      <button
        type="button"
        onClick={save}
        disabled={busy || !value.trim()}
        className="rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm font-medium text-primary transition hover:bg-primary/15 disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "记下"}
      </button>
    </div>
  );
}

function TodayBoard({
  state,
  setState,
}: {
  state: GrowthState;
  setState: (s: GrowthState) => void;
}) {
  const overview = state.overview!;
  const allDone = overview.done_today === overview.domain_count;

  const call = async (fn: () => Promise<GrowthState>) => {
    try {
      setState(await fn());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const reset = async () => {
    if (!window.confirm("重新来过会清掉现在的计划和打卡记录,确定吗?")) return;
    try {
      await api.resetGrowth();
      setState({ configured: false });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重置失败");
    }
  };

  return (
    <div className="space-y-6">
      <Lede>
        {allDone
          ? "今天四项都做完了。明天见。"
          : `今天还剩 ${overview.domain_count - overview.done_today} 项,每项几分钟。`}
      </Lede>

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-2xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">连续</p>
          <p className="mt-1 inline-flex items-baseline gap-1">
            <span className="text-2xl font-semibold tabular-nums">{overview.streak}</span>
            <span className="text-xs text-muted-foreground">天</span>
            {overview.streak >= 3 && <Flame className="h-3.5 w-3.5 text-primary" />}
          </p>
        </div>
        <div className="rounded-2xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">今天</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {overview.done_today}
            <span className="text-xs font-normal text-muted-foreground"> / {overview.domain_count}</span>
          </p>
        </div>
        <div className="rounded-2xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">距检查点</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {overview.checkpoint.days_left}
            <span className="text-xs font-normal text-muted-foreground"> 天</span>
          </p>
        </div>
      </div>

      {overview.nudge && (
        <p className="rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground">
          断了两天。不用补回来,从今天的最小版本重新开始就行。
        </p>
      )}

      <div className="space-y-4">
        {overview.domains.map((item) => (
          <DomainCard
            key={item.domain}
            item={item}
            onCheckin={async (domain, feeling) => call(() => api.growthCheckin(domain, feeling))}
            onUndo={async (domain) => call(() => api.growthUndoCheckin(domain))}
          />
        ))}
      </div>

      <CheckpointPanel
        state={state}
        onSave={async (domain, which, value) => call(() => api.growthSetCheckpoint(domain, which, value))}
      />

      <button
        type="button"
        onClick={reset}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
      >
        <RotateCcw className="h-3 w-3" />重新排一份计划
      </button>
    </div>
  );
}

// ── 页面 ─────────────────────────────────────────────────────────────────────

const TABS = [
  { key: "today", label: "每天", icon: Sprout },
  { key: "english", label: "英语句型", icon: MessagesSquare },
] as const;

type Tab = (typeof TABS)[number]["key"];

//  英语句型下的两件事:先学,再考。测验是学习的一部分,所以收在它里面。
const ENGLISH_VIEWS = [
  { key: "learn", label: "学习", icon: MessagesSquare },
  { key: "quiz", label: "测试", icon: Target },
] as const;

type EnglishView = (typeof ENGLISH_VIEWS)[number]["key"];

const tabClass = (active: boolean) =>
  cn(
    "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-colors",
    active ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
  );

export function Growth() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("tab");
  const tab: Tab = raw === "english" ? "english" : "today";
  const view: EnglishView = searchParams.get("view") === "quiz" ? "quiz" : "learn";
  const [state, setState] = useState<GrowthState | null>(null);
  const [options, setOptions] = useState<GrowthOptions | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [opts, current] = await Promise.all([api.getGrowthOptions(), api.getGrowthState()]);
      setOptions(opts);
      setState(current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 生成期间轮询,每排好一个领域进度条就前进一格。
  useEffect(() => {
    if (!state?.generating) return;
    const timer = window.setInterval(() => {
      void api.getGrowthState().then(setState).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [state?.generating]);

  const selectTab = (nextTab: Tab) => {
    const params = new URLSearchParams(searchParams);
    if (nextTab === "today") params.delete("tab");
    else params.set("tab", nextTab);
    params.delete("view");
    setSearchParams(params, { replace: true });
  };

  const selectView = (nextView: EnglishView) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", "english");
    if (nextView === "learn") params.delete("view");
    else params.set("view", nextView);
    setSearchParams(params, { replace: true });
  };

  const shell = (children: React.ReactNode) => (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-7 sm:px-6 sm:py-9">
      <div role="tablist" aria-label="成长栏目" className="inline-flex rounded-lg border bg-muted/30 p-1">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => selectTab(key)}
            className={tabClass(tab === key)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>
      {children}
    </div>
  );

  if (tab === "english") {
    return shell(
      <>
        <div role="tablist" aria-label="英语句型" className="inline-flex rounded-lg border bg-muted/30 p-1">
          {ENGLISH_VIEWS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              onClick={() => selectView(key)}
              className={tabClass(view === key)}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
        {view === "quiz" ? <EnglishQuiz /> : <EnglishDrill />}
      </>,
    );
  }

  if (error) {
    return shell(
      <>
        <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          {error}
        </p>
      </>,
    );
  }

  if (!state || !options) {
    return shell(
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />载入中…
      </div>,
    );
  }

  if (state.generating) {
    return shell(<Generating ready={state.ready ?? 0} total={state.total ?? 0} />);
  }

  return shell(
    state.configured
      ? <TodayBoard state={state} setState={setState} />
      : <Setup options={options} onCreated={setState} />,
  );
}
