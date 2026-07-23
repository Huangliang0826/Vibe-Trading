/** 学习进度持久化:单 key、带版本号,便于将来迁移。
 *
 * 新增字段只要给出安全默认值即可保持 version 1 —— 旧数据缺字段时回退为空,
 * 无需破坏性迁移。
 */

export const PROGRESS_KEY = "qa-learning-progress";

/** Leitner 盒子的复习间隔(毫秒):盒 1→1天,盒 2→3天,盒 3→7天 */
export const BOX_INTERVAL_MS: Record<1 | 2 | 3, number> = {
  1: 1 * 24 * 60 * 60 * 1000,
  2: 3 * 24 * 60 * 60 * 1000,
  3: 7 * 24 * 60 * 60 * 1000,
};

export interface QuizStat {
  /** Leitner 盒编号 1/2/3,盒越大复习间隔越长 */
  box: 1 | 2 | 3;
  /** 下次到期复习的时间戳(ms) */
  due: number;
  correct: number;
  wrong: number;
  /** 最近一次答题时间戳(ms) */
  lastAt: number;
}

export interface LearningProgress {
  version: 1;
  /** cardId -> 首次学完时间戳(ms) */
  read: Record<string, number>;
  favorites: string[];
  quiz: Record<string, QuizStat>;
  /** topicId -> 上次浏览到的 cardId,用于"继续学习" */
  lastVisited: Record<string, string>;
  /** 'YYYY-MM-DD' -> 当日学习/复习动作次数,用于热力日历与连续天数 */
  activity: Record<string, number>;
}

export function emptyProgress(): LearningProgress {
  return { version: 1, read: {}, favorites: [], quiz: {}, lastVisited: {}, activity: {} };
}

function asRecord<T>(v: unknown): Record<string, T> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, T>) : {};
}

/** 解析并校验存储内容;损坏或版本不认识时回退到空进度,绝不抛错。 */
export function parseProgress(raw: string | null): LearningProgress {
  if (!raw) return emptyProgress();
  try {
    const data = JSON.parse(raw) as Partial<LearningProgress>;
    if (!data || typeof data !== "object" || data.version !== 1) return emptyProgress();
    return {
      version: 1,
      read: asRecord<number>(data.read),
      favorites: Array.isArray(data.favorites) ? data.favorites.filter((v) => typeof v === "string") : [],
      quiz: asRecord<QuizStat>(data.quiz),
      lastVisited: asRecord<string>(data.lastVisited),
      activity: asRecord<number>(data.activity),
    };
  } catch {
    return emptyProgress();
  }
}

export function loadProgress(): LearningProgress {
  return parseProgress(localStorage.getItem(PROGRESS_KEY));
}

export function saveProgress(p: LearningProgress): void {
  try {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(p));
  } catch {
    /* 存储满或隐私模式,静默降级为仅内存 */
  }
}

/** 本地时区的日期键 'YYYY-MM-DD' */
export function dayKey(ts: number): string {
  const d = new Date(ts);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function bumpActivity(p: LearningProgress, now: number): Record<string, number> {
  const key = dayKey(now);
  return { ...p.activity, [key]: (p.activity[key] ?? 0) + 1 };
}

export function markRead(p: LearningProgress, cardId: string, now = Date.now()): LearningProgress {
  if (p.read[cardId]) return p;
  return { ...p, read: { ...p.read, [cardId]: now }, activity: bumpActivity(p, now) };
}

export function toggleFavorite(p: LearningProgress, cardId: string): LearningProgress {
  const has = p.favorites.includes(cardId);
  return {
    ...p,
    favorites: has ? p.favorites.filter((id) => id !== cardId) : [...p.favorites, cardId],
  };
}

export function setLastVisited(p: LearningProgress, topicId: string, cardId: string): LearningProgress {
  if (p.lastVisited[topicId] === cardId) return p;
  return { ...p, lastVisited: { ...p.lastVisited, [topicId]: cardId } };
}

/**
 * 记录一次测验结果并推进 Leitner 盒子。
 * - 答对且有把握:升一盒(最多 3),拉长下次复习间隔
 * - 答对但靠蒙:留在原盒,按原盒间隔复习(避免把"运气对"当"掌握")
 * - 答错:打回盒 1,尽快再复习
 */
export function recordQuizResult(
  p: LearningProgress,
  cardId: string,
  correct: boolean,
  confident: boolean,
  now = Date.now(),
): LearningProgress {
  const prev: QuizStat = p.quiz[cardId] ?? { box: 1, due: now, correct: 0, wrong: 0, lastAt: 0 };
  let box = prev.box;
  if (!correct) box = 1;
  else if (confident) box = Math.min(3, prev.box + 1) as 1 | 2 | 3;
  // 答对但没把握:box 不变

  const next: QuizStat = {
    box,
    due: now + BOX_INTERVAL_MS[box],
    correct: prev.correct + (correct ? 1 : 0),
    wrong: prev.wrong + (correct ? 0 : 1),
    lastAt: now,
  };
  return { ...p, quiz: { ...p.quiz, [cardId]: next }, activity: bumpActivity(p, now) };
}
