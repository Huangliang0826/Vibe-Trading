/** 个人成长模块(第一期):目标引擎、聚焦管理器、晚间签到、每周复盘。
 *
 * 设计依据:AlPAMind 个人成长模块功能设计方案。数据存浏览器 localStorage,单 key 带版本号;
 * 所有判定逻辑都是纯函数,便于测试。
 */

export const GROWTH_KEY = "qa-growth-v1";

export type GoalRole = "main" | "maintain" | "paused";
export type PracticeKind = "input" | "output";
export const BLOCKERS = ["没时间", "没动力", "太累", "方法不清", "被打断", "没有"] as const;
export type Blocker = (typeof BLOCKERS)[number];

export const MAX_MAIN = 1;
export const MAX_MAINTAIN = 3;

export interface Goal {
  id: string;
  domain: string;
  /** 可观察的结果 */
  outcome: string;
  /** 测量方法 */
  measure: string;
  /** 截止日期 YYYY-MM-DD */
  deadline: string;
  role: GoalRole;
  /** 维持目标的最低剂量 */
  dose: string;
  /** 所需投入估算(小时),可选 */
  estimateHours: number | null;
  /** 3 个月度里程碑 */
  milestones: string[];
  /** 每周投入目标(分钟)——是投入量而不是结果 */
  weeklyMinutes: number;
  /** 执行意图:什么时间、地点、做完什么之后,我就做什么 */
  intention: string;
  /** 2 分钟最小版本 */
  minVersion: string;
  createdAt: string;
}

export interface DailyLog {
  date: string;
  goalId: string;
  minutes: number;
  kind: PracticeKind;
  /** 1(很轻松)~5(很吃力) */
  difficulty: number;
  /** 维持目标是否完成最低剂量;无维持目标时为 null */
  maintainDone: boolean | null;
  blocker: Blocker;
  win: string;
}

export interface GrowthData {
  version: 1;
  goals: Goal[];
  logs: DailyLog[];
}

export const emptyGrowth = (): GrowthData => ({ version: 1, goals: [], logs: [] });

export function parseGrowth(raw: string | null): GrowthData {
  if (!raw) return emptyGrowth();
  try {
    const d = JSON.parse(raw) as Partial<GrowthData>;
    if (!d || d.version !== 1) return emptyGrowth();
    return {
      version: 1,
      goals: Array.isArray(d.goals) ? d.goals : [],
      logs: Array.isArray(d.logs) ? d.logs : [],
    };
  } catch {
    return emptyGrowth();
  }
}

export function loadGrowth(): GrowthData {
  try {
    return parseGrowth(localStorage.getItem(GROWTH_KEY));
  } catch {
    return emptyGrowth();
  }
}

export function saveGrowth(data: GrowthData): void {
  try {
    localStorage.setItem(GROWTH_KEY, JSON.stringify(data));
  } catch {
    /* 存储不可用时静默降级 */
  }
}

// ---------- 日期工具(本地时区,避免 toISOString 的 UTC 偏移) ----------

export function ymd(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function parseYmd(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(s: string, n: number): string {
  const d = parseYmd(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
}

// ---------- 目标引擎:校验器 ----------

export interface GoalDraft {
  domain: string;
  outcome: string;
  measure: string;
  deadline: string;
  role: GoalRole;
  dose: string;
  estimateHours: number | null;
  milestones: string[];
  weeklyMinutes: number;
  intention: string;
  minVersion: string;
}

/** 目标必须同时有"可观察的结果、测量方法、截止日期",缺一项不允许保存。 */
export function validateGoal(g: GoalDraft, today: string): string[] {
  const errs: string[] = [];
  if (!g.domain.trim()) errs.push("请填写领域(如 荷兰语、健身)");
  if (!g.outcome.trim()) errs.push("缺少可观察的结果:做到时是什么样子?");
  if (!g.measure.trim()) errs.push("缺少测量方法:怎么测?");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(g.deadline)) errs.push("缺少截止日期:什么时候?");
  else if (g.deadline < today) errs.push("截止日期不能早于今天");
  if (g.role === "maintain" && !g.dose.trim()) errs.push("维持目标必须定义最低剂量");
  if (g.role !== "maintain") {
    if (!(g.weeklyMinutes > 0)) errs.push("每周目标必须是投入量(分钟),而不是结果");
    if (!g.intention.trim()) errs.push("请写执行意图:在什么时间、地点、做完什么之后,我就做什么");
  }
  return errs;
}

// ---------- 聚焦管理器:准入规则 ----------

export function countRole(goals: Goal[], role: GoalRole): number {
  return goals.filter((g) => g.role === role).length;
}

/** 返回 null 表示可准入;否则给出必须先降级/暂停的提示。excludeId 用于编辑已有目标。 */
export function admissionBlock(goals: Goal[], role: GoalRole, excludeId?: string): string | null {
  const others = goals.filter((g) => g.id !== excludeId);
  if (role === "main" && countRole(others, "main") >= MAX_MAIN)
    return "已有 1 个主攻目标:请先把它降级为维持或暂停,并想清楚理由。";
  if (role === "maintain" && countRole(others, "maintain") >= MAX_MAINTAIN)
    return "维持目标已满 3 个:请先暂停一个维持目标。";
  return null;
}

// ---------- 每周复盘 ----------

export interface WeeklyReview {
  weekStart: string;
  weekEnd: string;
  plannedMinutes: number;
  doneMinutes: number;
  /** 完成率 %,无计划时为 null */
  completion: number | null;
  prevCompletion: number | null;
  topBlocker: { blocker: Blocker; count: number } | null;
  forecast: { date: string; late: boolean } | null;
  /** 唯一调整 */
  adjustment: string;
  highlight: string | null;
  loggedDays: number;
}

function minutesIn(logs: DailyLog[], goalId: string, from: string, to: string): number {
  return logs
    .filter((l) => l.goalId === goalId && l.date >= from && l.date <= to)
    .reduce((s, l) => s + l.minutes, 0);
}

/** 按过去 4 周平均投入预测达成日期;无估算或无投入时返回 null。 */
export function forecastDate(goal: Goal, logs: DailyLog[], today: string): { date: string; late: boolean } | null {
  if (!goal.estimateHours) return null;
  const total = logs.filter((l) => l.goalId === goal.id).reduce((s, l) => s + l.minutes, 0);
  const recent = minutesIn(logs, goal.id, addDays(today, -27), today);
  const perDay = recent / 28;
  if (perDay <= 0) return null;
  const remaining = Math.max(0, goal.estimateHours * 60 - total);
  const date = addDays(today, Math.ceil(remaining / perDay));
  return { date, late: date > goal.deadline };
}

/** 复盘窗口为 today 往前 7 天(含 today)。只针对主攻目标,周报只给一个调整。 */
export function buildWeeklyReview(data: GrowthData, today: string): WeeklyReview | null {
  const main = data.goals.find((g) => g.role === "main");
  if (!main) return null;
  const weekStart = addDays(today, -6);
  const prevStart = addDays(today, -13);
  const prevEnd = addDays(today, -7);
  const done = minutesIn(data.logs, main.id, weekStart, today);
  const prevDone = minutesIn(data.logs, main.id, prevStart, prevEnd);
  const planned = main.weeklyMinutes;
  const hasPrev = data.logs.some((l) => l.goalId === main.id && l.date >= prevStart && l.date <= prevEnd);
  const week = data.logs.filter((l) => l.date >= weekStart && l.date <= today);

  const counts = new Map<Blocker, number>();
  for (const l of week) if (l.blocker !== "没有") counts.set(l.blocker, (counts.get(l.blocker) ?? 0) + 1);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  const topBlocker = top ? { blocker: top[0], count: top[1] } : null;

  const mainWeek = week.filter((l) => l.goalId === main.id);
  const outputShare = mainWeek.length
    ? mainWeek.filter((l) => l.kind === "output").reduce((s, l) => s + l.minutes, 0) / Math.max(1, done)
    : null;
  const lowStreak = mainWeek.length >= 3 && mainWeek.slice(-3).every((l) => l.difficulty <= 2);
  const highStreak = mainWeek.length >= 3 && mainWeek.slice(-3).every((l) => l.difficulty >= 5);

  const completion = planned > 0 ? Math.round((done / planned) * 100) : null;
  const forecast = forecastDate(main, data.logs, today);

  let adjustment: string;
  if (mainWeek.length === 0) adjustment = "下周只改一件事:先把每天的最小版本做起来,保住节奏。";
  else if (completion !== null && completion < 80)
    adjustment = topBlocker
      ? `下周只改一件事:针对「${topBlocker.blocker}」(本周 ${topBlocker.count} 天),把执行意图安排到更稳定的时段。`
      : "下周只改一件事:把执行意图安排到更稳定的时段。";
  else if (lowStreak) adjustment = "下周只改一件事:最近 3 次难度都不超过 2 分,把练习难度提高一档。";
  else if (highStreak) adjustment = "下周只改一件事:最近 3 次都是 5 分,把练习退一档,避免挫败。";
  else if (outputShare !== null && outputShare < 0.3)
    adjustment = "下周只改一件事:输出(说、写、训练)占比低于 30%,把一半输入时间换成输出。";
  else adjustment = "投入达标。下周只改一件事:保持节奏,不加量。";

  const wins = week.filter((l) => l.win.trim());
  const highlight = wins.length ? wins[wins.length - 1].win.trim() : null;

  return {
    weekStart,
    weekEnd: today,
    plannedMinutes: planned,
    doneMinutes: done,
    completion,
    prevCompletion: planned > 0 && hasPrev ? Math.round((prevDone / planned) * 100) : null,
    topBlocker,
    forecast,
    adjustment,
    highlight,
    loggedDays: new Set(week.map((l) => l.date)).size,
  };
}

/** "不连续断两次":断一天不提醒,只有连续断两天(昨天和前天都没记录)才提醒。 */
export function missedTwoDays(logs: DailyLog[], today: string): boolean {
  const dates = new Set(logs.map((l) => l.date));
  return !dates.has(addDays(today, -1)) && !dates.has(addDays(today, -2)) && logs.length > 0;
}

export function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}
