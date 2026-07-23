import { useMemo } from "react";
import { Flame, GraduationCap, Star, Target, TrendingDown, CalendarDays } from "lucide-react";
import { TOPICS } from "@/lib/learning/topics";
import { CARDS_BY_TOPIC, ALL_CARDS } from "@/lib/learning/content";
import type { LearningProgress } from "@/lib/learning/progress";
import { overallStats, topicStats, activityHeatmap, weakestTopic } from "@/lib/learning/stats";
import { MasteryRadar } from "./MasteryRadar";
import { ActivityHeatmap } from "./ActivityHeatmap";

function StatTile({
  icon: Icon,
  value,
  label,
  accent = "text-primary",
}: {
  icon: typeof Flame;
  value: string;
  label: string;
  accent?: string;
}) {
  return (
    <div className="soft-card rounded-2xl p-4">
      <Icon className={`h-4 w-4 ${accent}`} strokeWidth={1.9} />
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{label}</p>
    </div>
  );
}

export function StatsPanel({ progress, onReview }: { progress: LearningProgress; onReview: () => void }) {
  const overall = useMemo(() => overallStats(progress, ALL_CARDS), [progress]);
  const tStats = useMemo(
    () => topicStats(progress, TOPICS.map((t) => ({ id: t.id, title: t.title })), CARDS_BY_TOPIC),
    [progress],
  );
  const heat = useMemo(() => activityHeatmap(progress.activity, 91), [progress.activity]);
  const weak = useMemo(() => weakestTopic(tStats), [tStats]);

  if (overall.totalRead === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed bg-card/60 px-6 py-16 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary">
          <GraduationCap className="h-5 w-5" strokeWidth={1.8} />
        </div>
        <p className="text-sm font-medium">还没有学习数据</p>
        <p className="max-w-sm text-xs leading-5 text-muted-foreground">
          去「学习」tab 学几条知识,这里就会长出一份关于你大脑的投研报告:掌握度雷达、学习热力日历与薄弱点诊断。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* 概览指标 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile icon={GraduationCap} value={`${overall.totalRead}/${overall.totalCards}`} label="已学知识" />
        <StatTile icon={Target} value={overall.accuracy === null ? "—" : `${overall.accuracy}%`} label="测验正确率" accent="text-accent" />
        <StatTile icon={Flame} value={`${overall.streak}`} label="连续学习(天)" accent="text-warning" />
        <StatTile icon={Star} value={`${overall.totalFavorites}`} label="收藏" accent="text-warning" />
      </div>

      {/* 掌握度雷达 */}
      <div className="soft-card rounded-2xl p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">掌握度雷达</h3>
          <span className="text-[11px] text-muted-foreground">已掌握 {overall.totalMastered} 条</span>
        </div>
        <MasteryRadar stats={tStats} />
      </div>

      {/* 知识资产负债表 */}
      <div className="soft-card rounded-2xl p-5">
        <h3 className="text-sm font-medium">知识资产负债表</h3>
        <p className="mt-0.5 text-[11px] text-muted-foreground">用你熟悉的金融语言,盘点你的学习状态</p>
        <div className="mt-4 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-xl bg-success/10 p-3">
            <p className="text-xl font-semibold text-success tabular-nums">{overall.totalMastered}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">资产 · 已掌握</p>
          </div>
          <div className="rounded-xl bg-red-500/10 p-3">
            <p className="text-xl font-semibold text-red-600 dark:text-red-400 tabular-nums">{overall.dueCount}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">负债 · 待复习</p>
          </div>
          <div className="rounded-xl bg-warning/10 p-3">
            <p className="text-xl font-semibold text-warning tabular-nums">
              {Math.max(0, progress.favorites.length)}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">应收 · 收藏待消化</p>
          </div>
        </div>
        {overall.dueCount > 0 && (
          <button
            type="button"
            onClick={onReview}
            className="mt-4 w-full rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-90"
          >
            去复习 {overall.dueCount} 条到期知识,把负债还清
          </button>
        )}
      </div>

      {/* 各主题进度条 */}
      <div className="soft-card rounded-2xl p-5">
        <h3 className="text-sm font-medium">各主题掌握度</h3>
        <div className="mt-4 space-y-3">
          {tStats.map((s) => (
            <div key={s.topicId}>
              <div className="flex items-center justify-between text-xs">
                <span>{s.title}</span>
                <span className="text-muted-foreground">
                  {s.accuracy !== null && <span className="mr-2">正确率 {s.accuracy}%</span>}
                  <span className="font-semibold text-foreground">{s.mastery}%</span>
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${s.mastery}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 学习热力日历 */}
      <div className="soft-card rounded-2xl p-5">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">学习热力(近 3 个月)</h3>
          <span className="ml-auto text-[11px] text-muted-foreground">累计活跃 {overall.activeDays} 天</span>
        </div>
        <div className="mt-4">
          <ActivityHeatmap cells={heat} />
        </div>
      </div>

      {/* 薄弱点诊断 */}
      {weak && weak.mastery < 100 && (
        <div className="rounded-2xl border border-warning/25 bg-warning/5 p-5">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-warning" />
            <h3 className="text-sm font-medium">薄弱点诊断</h3>
          </div>
          <p className="mt-2 text-sm leading-6 text-foreground/85">
            你在「<span className="font-medium">{weak.title}</span>」的掌握度最低,为 {weak.mastery}%
            {weak.accuracy !== null && weak.accuracy < 70 && <>,测验正确率仅 {weak.accuracy}%</>}。
            建议重点回顾这个主题,并多做几轮复习巩固。
          </p>
        </div>
      )}
    </div>
  );
}
