/** 跨设备学习进度同步。
 *
 * 进度与 AI 卡片仍以 localStorage 为本地缓存(离线可用),同时镜像到后端的单用户
 * 共享状态,实现手机 / 网页同步。合并采用无损并集,避免任一端覆盖另一端的进度。
 */
import { api } from "@/lib/api";
import {
  PROGRESS_KEY,
  parseProgress,
  type LearningProgress,
  type QuizStat,
} from "./progress";
import { EXTRA_KEY, parseExtra, type ExtraByTopic } from "./extra-store";
import type { KnowledgeCard, TopicId } from "./types";

/** 合并两份进度:读过取最早时间、收藏取并集、测验取最近一次、活跃取每日最大。 */
export function mergeProgress(a: LearningProgress, b: LearningProgress): LearningProgress {
  const read: Record<string, number> = { ...b.read };
  for (const [k, v] of Object.entries(a.read)) {
    read[k] = k in read ? Math.min(read[k], v) : v;
  }
  const favorites = Array.from(new Set([...a.favorites, ...b.favorites]));

  const quiz: Record<string, QuizStat> = { ...b.quiz };
  for (const [k, v] of Object.entries(a.quiz)) {
    const other = quiz[k];
    quiz[k] = !other || v.lastAt >= other.lastAt ? v : other;
  }

  const activity: Record<string, number> = { ...b.activity };
  for (const [k, v] of Object.entries(a.activity)) {
    activity[k] = Math.max(activity[k] ?? 0, v);
  }

  // lastVisited 无时间戳,优先保留 a(本地当前设备)的续读位置
  const lastVisited: Record<string, string> = { ...b.lastVisited, ...a.lastVisited };

  return { version: 1, read, favorites, quiz, lastVisited, activity };
}

/** 合并 AI 卡片:按 id 去重(id 含时间戳,排序后保持时间顺序)。 */
export function mergeExtra(a: ExtraByTopic, b: ExtraByTopic): ExtraByTopic {
  const out: ExtraByTopic = {};
  const topics = new Set<string>([...Object.keys(a), ...Object.keys(b)]);
  for (const t of topics) {
    const byId = new Map<string, KnowledgeCard>();
    for (const c of a[t as TopicId] ?? []) byId.set(c.id, c);
    for (const c of b[t as TopicId] ?? []) byId.set(c.id, c);
    const cards = Array.from(byId.values()).sort((x, y) => x.id.localeCompare(y.id));
    if (cards.length) out[t as TopicId] = cards;
  }
  return out;
}

let pushTimer: ReturnType<typeof setTimeout> | undefined;

/** 防抖地把当前本地状态(进度 + AI 卡片)推送到后端;失败静默(本地仍可用)。 */
export function schedulePush(delayMs = 1200): void {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    let progress: unknown = null;
    let extra: unknown = null;
    try {
      progress = JSON.parse(localStorage.getItem(PROGRESS_KEY) || "null");
      extra = JSON.parse(localStorage.getItem(EXTRA_KEY) || "null");
    } catch {
      /* 本地损坏则不推送 */
      return;
    }
    api.putLearningState({ progress, extra }).catch(() => {});
  }, delayMs);
}

export interface MergedState {
  progress: LearningProgress;
  extra: ExtraByTopic;
}

/**
 * 拉取后端状态并与本地合并。返回合并结果供调用方应用;网络失败返回 null(离线)。
 */
export async function pullAndMerge(
  localProgress: LearningProgress,
  localExtra: ExtraByTopic,
): Promise<MergedState | null> {
  let remote: { progress: unknown; extra: unknown };
  try {
    remote = await api.getLearningState();
  } catch {
    return null;
  }
  const remoteProgress = remote?.progress
    ? parseProgress(JSON.stringify(remote.progress))
    : null;
  const remoteExtra = parseExtra(remote?.extra);

  return {
    progress: remoteProgress ? mergeProgress(localProgress, remoteProgress) : localProgress,
    extra: mergeExtra(localExtra, remoteExtra),
  };
}
