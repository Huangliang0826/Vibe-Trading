import type { KnowledgeCard, TopicId } from "./types";
import type { LearningProgress } from "./progress";

export interface ReviewItem {
  card: KnowledgeCard;
  /** 是否为到期需复习(已测过且已到期);false 表示尚未测过的新题 */
  due: boolean;
}

/**
 * 构建复习队列(仅在已学过的卡片中出题):
 * 优先级 1)到期且历史答错多的(box 低、wrong 多)
 *        2)到期的其它题
 *        3)学过但从未测过的新题
 * 未到期且已答对过的题不进入队列(间隔重复的意义所在)。
 */
export function buildReviewQueue(
  progress: LearningProgress,
  cards: KnowledgeCard[],
  topic: TopicId | "all",
  now = Date.now(),
): ReviewItem[] {
  const pool = cards.filter(
    (c) => progress.read[c.id] && (topic === "all" || c.topicId === topic),
  );

  const dueItems: { card: KnowledgeCard; score: number }[] = [];
  const freshItems: KnowledgeCard[] = [];

  for (const card of pool) {
    const stat = progress.quiz[card.id];
    if (!stat) {
      freshItems.push(card);
      continue;
    }
    if (stat.due <= now) {
      // 分数越大越优先:盒子越低越优先,答错越多越优先,过期越久越优先
      const overdue = (now - stat.due) / (24 * 60 * 60 * 1000);
      const score = (4 - stat.box) * 100 + stat.wrong * 10 + Math.min(overdue, 30);
      dueItems.push({ card, score });
    }
  }

  dueItems.sort((a, b) => b.score - a.score);

  return [
    ...dueItems.map((d) => ({ card: d.card, due: true })),
    ...freshItems.map((c) => ({ card: c, due: false })),
  ];
}

/** 统计当前有多少题"到期待复习"(用于 tab 上的红点提示) */
export function countDueReviews(
  progress: LearningProgress,
  cards: KnowledgeCard[],
  now = Date.now(),
): number {
  let n = 0;
  for (const card of cards) {
    if (!progress.read[card.id]) continue;
    const stat = progress.quiz[card.id];
    if (stat && stat.due <= now) n++;
  }
  return n;
}

/** Fisher–Yates 洗牌,返回新数组 */
export function shuffle<T>(arr: T[], rand: () => number = Math.random): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * 为一道题生成 4 个打乱后的选项,并返回正确项的新下标。
 * 用题目 id 派生一个稳定的伪随机种子,让同一题的选项顺序在一次会话里保持稳定。
 */
export function shuffledOptions(card: KnowledgeCard): { options: string[]; answer: number } {
  const idx = card.quiz.options.map((_, i) => i);
  // 稳定种子:题目 id 的字符和
  let seed = 0;
  for (const ch of card.id) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0xffffffff;
  };
  const order = shuffle(idx, rand);
  return {
    options: order.map((i) => card.quiz.options[i]),
    answer: order.indexOf(card.quiz.answer),
  };
}
