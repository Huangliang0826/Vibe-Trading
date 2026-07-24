/** AI 出题的本地缓存(按知识点 id 存一道题)。
 *
 * 纯性能缓存:提前批量生成后存这里,复习时即时取用、零等待;可随时重建,故不参与
 * 跨设备同步,只留在本地 localStorage。
 */
import type { GeneratedQuiz } from "@/lib/api";

export const AIQUIZ_KEY = "qa-learning-aiquiz";

export type AiQuizCache = Record<string, GeneratedQuiz>;

function isValid(q: unknown): q is GeneratedQuiz {
  if (!q || typeof q !== "object") return false;
  const x = q as Record<string, unknown>;
  return (
    typeof x.question === "string" &&
    Array.isArray(x.options) &&
    typeof x.answer === "number" &&
    typeof x.explanation === "string"
  );
}

export function loadAiQuizCache(): AiQuizCache {
  try {
    const raw = localStorage.getItem(AIQUIZ_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (!data || typeof data !== "object") return {};
    const out: AiQuizCache = {};
    for (const [id, q] of Object.entries(data)) if (isValid(q)) out[id] = q;
    return out;
  } catch {
    return {};
  }
}

export function saveAiQuizCache(cache: AiQuizCache): void {
  try {
    localStorage.setItem(AIQUIZ_KEY, JSON.stringify(cache));
  } catch {
    /* 存储满则忽略 */
  }
}

export function mergeIntoAiQuizCache(
  cache: AiQuizCache,
  entries: { id: string; quiz: GeneratedQuiz }[],
): AiQuizCache {
  const next = { ...cache };
  for (const e of entries) if (isValid(e.quiz)) next[e.id] = e.quiz;
  saveAiQuizCache(next);
  return next;
}
