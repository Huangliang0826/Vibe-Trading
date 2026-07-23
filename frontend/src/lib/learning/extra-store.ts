/** AI 扩充的知识卡片持久化(与内置题库分开存储,运行时合并)。
 *
 * 卡片 id 一经生成即固定(带时间戳),保证学习进度、复习盒子等以 id 为键的数据
 * 不会因重新加载而错位。
 */
import type { KnowledgeCard, TopicId, CardType } from "./types";
import type { GeneratedCard } from "@/lib/api";

export const EXTRA_KEY = "qa-learning-extra";

export type ExtraByTopic = Partial<Record<TopicId, KnowledgeCard[]>>;

const VALID_TYPES: CardType[] = ["concept", "story", "pitfall"];

function sanitizeCard(raw: unknown, topicId: TopicId): KnowledgeCard | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  const id = typeof c.id === "string" ? c.id : "";
  const title = typeof c.title === "string" ? c.title : "";
  const core = typeof c.core === "string" ? c.core : "";
  const quiz = c.quiz as KnowledgeCard["quiz"] | undefined;
  if (!id || !title || !core || !quiz || !Array.isArray(quiz.options)) return null;
  const type = (VALID_TYPES as string[]).includes(c.type as string) ? (c.type as CardType) : "concept";
  const difficulty = ([1, 2, 3] as unknown[]).includes(c.difficulty) ? (c.difficulty as 1 | 2 | 3) : 2;
  return {
    id,
    topicId,
    type,
    difficulty,
    title,
    core,
    example: typeof c.example === "string" ? c.example : undefined,
    pitfall: typeof c.pitfall === "string" ? c.pitfall : undefined,
    aiGenerated: true,
    quiz,
  };
}

/** 把任意对象(本地字符串或远端已解析对象)规整为合法的 ExtraByTopic。 */
export function parseExtra(input: unknown): ExtraByTopic {
  try {
    const data = (typeof input === "string" ? JSON.parse(input) : input) as Record<string, unknown> | null;
    if (!data || typeof data !== "object") return {};
    const out: ExtraByTopic = {};
    for (const [topic, list] of Object.entries(data)) {
      if (!Array.isArray(list)) continue;
      const cards = list
        .map((c) => sanitizeCard(c, topic as TopicId))
        .filter((c): c is KnowledgeCard => Boolean(c));
      if (cards.length) out[topic as TopicId] = cards;
    }
    return out;
  } catch {
    return {};
  }
}

export function loadExtra(): ExtraByTopic {
  return parseExtra(localStorage.getItem(EXTRA_KEY));
}

export function saveExtra(data: ExtraByTopic): void {
  try {
    localStorage.setItem(EXTRA_KEY, JSON.stringify(data));
  } catch {
    /* 存储满或隐私模式,静默降级为仅内存 */
  }
}

/** 把后端生成的卡片补齐 id/topicId,追加到某主题下并持久化;返回新增的卡片。 */
export function appendGeneratedCards(
  current: ExtraByTopic,
  topicId: TopicId,
  generated: GeneratedCard[],
  now = Date.now(),
): { next: ExtraByTopic; added: KnowledgeCard[] } {
  const existing = current[topicId] ?? [];
  const added: KnowledgeCard[] = generated.map((g, i) => ({
    id: `${topicId}-ai-${now}-${i}`,
    topicId,
    type: (VALID_TYPES as string[]).includes(g.type) ? (g.type as CardType) : "concept",
    difficulty: ([1, 2, 3] as number[]).includes(g.difficulty) ? (g.difficulty as 1 | 2 | 3) : 2,
    title: g.title,
    core: g.core,
    example: g.example ?? undefined,
    pitfall: g.pitfall ?? undefined,
    aiGenerated: true,
    quiz: {
      type: g.quiz.type,
      question: g.quiz.question,
      options: g.quiz.options,
      answer: g.quiz.answer,
      explanation: g.quiz.explanation,
    },
  }));
  const next: ExtraByTopic = { ...current, [topicId]: [...existing, ...added] };
  saveExtra(next);
  return { next, added };
}
