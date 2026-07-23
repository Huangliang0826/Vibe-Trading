import type { KnowledgeCard, TopicId } from "./types";
import type { LearningProgress } from "./progress";
import { dayKey } from "./progress";

export interface TopicStat {
  topicId: TopicId;
  title: string;
  total: number;
  read: number;
  /** 已测过并"掌握"(box>=2 或至少答对一次且最近一次答对)的数量 */
  mastered: number;
  /** 掌握度 0-100:综合已学与已掌握 */
  mastery: number;
  /** 该主题测验正确率 0-100(无测验记录时为 null) */
  accuracy: number | null;
}

/** 判定一张卡片是否"已掌握":测验盒子达到 2 及以上 */
export function isMastered(progress: LearningProgress, cardId: string): boolean {
  const stat = progress.quiz[cardId];
  return Boolean(stat && stat.box >= 2);
}

export function topicStats(
  progress: LearningProgress,
  topics: { id: TopicId; title: string }[],
  cardsByTopic: Record<TopicId, KnowledgeCard[]>,
): TopicStat[] {
  return topics.map((t) => {
    const cards = cardsByTopic[t.id] ?? [];
    const total = cards.length;
    const read = cards.filter((c) => progress.read[c.id]).length;
    const mastered = cards.filter((c) => isMastered(progress, c.id)).length;
    let correct = 0;
    let attempts = 0;
    for (const c of cards) {
      const s = progress.quiz[c.id];
      if (s) {
        correct += s.correct;
        attempts += s.correct + s.wrong;
      }
    }
    // 掌握度:已学占 60%,已掌握占 40%
    const mastery = total === 0 ? 0 : Math.round(((read / total) * 0.6 + (mastered / total) * 0.4) * 100);
    return {
      topicId: t.id,
      title: t.title,
      total,
      read,
      mastered,
      mastery,
      accuracy: attempts === 0 ? null : Math.round((correct / attempts) * 100),
    };
  });
}

export interface OverallStats {
  totalCards: number;
  totalRead: number;
  totalMastered: number;
  totalFavorites: number;
  /** 测验总正确率 0-100,无记录为 null */
  accuracy: number | null;
  attempts: number;
  /** 连续学习天数(含今天) */
  streak: number;
  /** 有学习活动的总天数 */
  activeDays: number;
  /** 待复习(到期)题数 */
  dueCount: number;
}

export function overallStats(
  progress: LearningProgress,
  allCards: KnowledgeCard[],
  now = Date.now(),
): OverallStats {
  const totalRead = allCards.filter((c) => progress.read[c.id]).length;
  const totalMastered = allCards.filter((c) => isMastered(progress, c.id)).length;
  let correct = 0;
  let attempts = 0;
  let dueCount = 0;
  for (const c of allCards) {
    const s = progress.quiz[c.id];
    if (s) {
      correct += s.correct;
      attempts += s.correct + s.wrong;
      if (progress.read[c.id] && s.due <= now) dueCount++;
    }
  }
  return {
    totalCards: allCards.length,
    totalRead,
    totalMastered,
    totalFavorites: progress.favorites.length,
    accuracy: attempts === 0 ? null : Math.round((correct / attempts) * 100),
    attempts,
    streak: currentStreak(progress.activity, now),
    activeDays: Object.keys(progress.activity).length,
    dueCount,
  };
}

/** 从今天(或昨天)起向前数连续有活动的天数 */
export function currentStreak(activity: Record<string, number>, now = Date.now()): number {
  const today = dayKey(now);
  const yesterday = dayKey(now - 24 * 60 * 60 * 1000);
  // 允许今天还没学(从昨天算起),但今天学了则从今天算
  let cursor: number;
  if (activity[today]) cursor = now;
  else if (activity[yesterday]) cursor = now - 24 * 60 * 60 * 1000;
  else return 0;

  let streak = 0;
  while (activity[dayKey(cursor)]) {
    streak++;
    cursor -= 24 * 60 * 60 * 1000;
  }
  return streak;
}

export interface HeatCell {
  date: string;
  count: number;
}

/** 返回最近 `days` 天(含今天)的活跃热力数据,从早到晚 */
export function activityHeatmap(
  activity: Record<string, number>,
  days = 91,
  now = Date.now(),
): HeatCell[] {
  const cells: HeatCell[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const ts = now - i * 24 * 60 * 60 * 1000;
    const key = dayKey(ts);
    cells.push({ date: key, count: activity[key] ?? 0 });
  }
  return cells;
}

/** 找出最薄弱的主题(掌握度最低且已开始学习的),用于诊断提示 */
export function weakestTopic(stats: TopicStat[]): TopicStat | null {
  const started = stats.filter((s) => s.read > 0);
  if (started.length === 0) return null;
  return started.reduce((min, s) => (s.mastery < min.mastery ? s : min), started[0]);
}
