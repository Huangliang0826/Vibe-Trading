/** 个人成长:每天的目标 + 两门语言的练习。
 *
 *  没有计划。早先这里由模型排一份两周计划,但"口头输出 15 分钟"这种描述
 *  自己判断不了做完没有。现在每门语言只有一个目标——在测验里答对几条——
 *  够数自动算完成,量的是结果而不是按没按按钮。
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Check, Flame, Languages, Loader2, MessagesSquare, Sprout } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  api, type DailyProgress, type GrowthCalendarDay, type GrowthState,
  type GrowthSummary,
} from "@/lib/api";
import { PracticeDrill } from "@/pages/growth/PracticeDrill";
import { PracticeQuiz } from "@/pages/growth/PracticeQuiz";

const TABS = [
  { key: "today", label: "每天", icon: Sprout },
  { key: "en", label: "英语", icon: MessagesSquare },
  { key: "nl", label: "荷兰语", icon: Languages },
] as const;

type Tab = (typeof TABS)[number]["key"];

const VIEWS = [
  { key: "learn", label: "学习" },
  { key: "quiz", label: "测试" },
] as const;

type View = (typeof VIEWS)[number]["key"];

const tabClass = (active: boolean) =>
  cn(
    "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-colors",
    active ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
  );

//  子栏目用更轻的下划线,和上面那排分段控件区分开——两排一样重的药丸会糊成一团。
const subTabClass = (active: boolean) =>
  cn(
    "border-b-2 pb-2 text-sm transition-colors",
    active
      ? "border-primary font-medium text-foreground"
      : "border-transparent text-muted-foreground hover:text-foreground",
  );

function Lede({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

/** 一门语言今天的目标。进度来自测验,所以没有"完成"按钮可按。 */
function LanguageCard({ item }: { item: DailyProgress & { key: string; label: string } }) {
  const pct = Math.min(100, Math.round((item.correct / Math.max(1, item.goal)) * 100));

  return (
    <div
      className={cn(
        "space-y-4 rounded-2xl border bg-card p-5 transition-colors",
        item.done && "border-primary/35 bg-primary/[0.04]",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[15px] font-medium">{item.label}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">{item.correct}</span> / {item.goal} 条
        </span>
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>

      <p className="text-sm leading-relaxed text-muted-foreground">
        {item.done
          ? `今天答对了 ${item.correct} 条,目标已经完成。`
          : `去「${item.label} → 测试」答对 ${item.goal} 条就算今天过了。`}
      </p>

      {item.done ? (
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
          <Check className="h-4 w-4" />今天完成
        </span>
      ) : (
        <Link
          to={`/growth?tab=${item.key}&view=quiz`}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary transition hover:bg-primary/15"
        >
          去测试<ArrowRight className="h-4 w-4" />
        </Link>
      )}
    </div>
  );
}

/** 打卡日历。两门都达标画实心,只达标一门画浅色——把"做了一半"也显示出来,
 *  比只认全勤诚实,也更不容易让人因为断一次就放弃。 */
function Calendar({ days, summary }: { days: GrowthCalendarDay[]; summary: GrowthSummary }) {
  return (
    <div className="space-y-4 rounded-2xl border bg-card p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-medium">打卡日历</h2>
        <span className="text-xs text-muted-foreground">最近四周</span>
      </div>

      <div className="grid grid-cols-7 gap-1.5">
        {days.map((day) => (
          <div
            key={day.date}
            title={`${day.date} · ${day.state === "full" ? "两门都达标" : day.state === "partial" ? "达标一门" : "未打卡"}`}
            className={cn(
              "aspect-square rounded-md",
              day.state === "full" && "bg-primary",
              day.state === "partial" && "bg-primary/30",
              day.state === "none" && "bg-muted-foreground/10",
            )}
          />
        ))}
      </div>

      <dl className="grid grid-cols-3 gap-3 border-t pt-4 text-center">
        {[
          { label: "累计打卡", value: summary.active_days },
          { label: "两门全勤", value: summary.full_days },
          { label: "最长连续", value: summary.best_streak },
        ].map((row) => (
          <div key={row.label}>
            <dt className="text-xs text-muted-foreground">{row.label}</dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {row.value}
              <span className="text-xs font-normal text-muted-foreground"> 天</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Today() {
  const [state, setState] = useState<GrowthState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.getGrowthState().then(setState)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);

  if (error) {
    return <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">{error}</p>;
  }
  if (!state) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />载入中…
      </div>
    );
  }

  const remaining = state.lang_count - state.done_today;

  return (
    <div className="space-y-6">
      <Lede>{remaining === 0 ? "今天都做完了。明天见。" : `今天还剩 ${remaining} 项,每项几分钟。`}</Lede>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">连续</p>
          <p className="mt-1 inline-flex items-baseline gap-1">
            <span className="text-2xl font-semibold tabular-nums">{state.streak}</span>
            <span className="text-xs text-muted-foreground">天</span>
            {state.streak >= 3 && <Flame className="h-3.5 w-3.5 text-primary" />}
          </p>
        </div>
        <div className="rounded-2xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">今天</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {state.done_today}
            <span className="text-xs font-normal text-muted-foreground"> / {state.lang_count}</span>
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {state.languages.map((item) => <LanguageCard key={item.key} item={item} />)}
      </div>

      <Calendar days={state.calendar} summary={state.summary} />
    </div>
  );
}

export function Growth() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("tab");
  const tab: Tab = raw === "en" || raw === "nl" ? raw : "today";
  const view: View = searchParams.get("view") === "quiz" ? "quiz" : "learn";
  const rawTrack = searchParams.get("track") ?? "";

  const [tracks, setTracks] = useState<{ key: string; label: string }[]>([]);

  // 分类由后端给:荷兰语没有「句型」,前端不该自己猜有哪几类。
  const loadTracks = useCallback(async () => {
    if (tab === "today") return;
    try {
      const data = await api.getPractice(tab);
      setTracks(data.tracks.map(({ key, label }) => ({ key, label })));
    } catch {
      setTracks([]);
    }
  }, [tab]);

  useEffect(() => {
    void loadTracks();
  }, [loadTracks]);

  const track = tracks.some((t) => t.key === rawTrack) ? rawTrack : (tracks[0]?.key ?? "");

  const setParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) params.delete(key);
      else params.set(key, value);
    }
    setSearchParams(params, { replace: true });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-7 sm:px-6 sm:py-9">
      <div role="tablist" aria-label="成长栏目" className="inline-flex rounded-lg border bg-muted/30 p-1">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setParams({ tab: key === "today" ? null : key, view: null, track: null })}
            className={tabClass(tab === key)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "today" ? (
        <Today />
      ) : !track ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />载入中…
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3 border-b">
            <div role="tablist" aria-label="栏目" className="flex gap-6">
              {VIEWS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={view === key}
                  onClick={() => setParams({ view: key === "learn" ? null : key })}
                  className={subTabClass(view === key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div role="tablist" aria-label="内容分类" className="mb-2 inline-flex rounded-lg border bg-muted/30 p-0.5">
              {tracks.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={track === key}
                  onClick={() => setParams({ track: key })}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs transition-colors",
                    track === key
                      ? "bg-background font-medium text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {/* key 让切换语言或分类时组件重建,队列和游标一起重置 */}
          {view === "quiz"
            ? <PracticeQuiz key={`${tab}-${track}`} lang={tab} track={track} />
            : <PracticeDrill key={`${tab}-${track}`} lang={tab} track={track} />}
        </>
      )}
    </div>
  );
}
