import { describe, it, expect } from "vitest";
import {
  admissionBlock,
  buildWeeklyReview,
  forecastDate,
  missedTwoDays,
  parseGrowth,
  validateGoal,
  type DailyLog,
  type Goal,
  type GoalDraft,
} from "../store";

const draft = (o: Partial<GoalDraft> = {}): GoalDraft => ({
  domain: "荷兰语",
  outcome: "能连续交谈15分钟",
  measure: "录音为证",
  deadline: "2026-12-31",
  role: "main",
  dose: "",
  estimateHours: null,
  milestones: ["", "", ""],
  weeklyMinutes: 180,
  intention: "每天早餐后,在书桌前,上30分钟课",
  minVersion: "听2分钟播客",
  ...o,
});

const goal = (o: Partial<Goal> = {}): Goal => ({
  ...draft(),
  id: "g1",
  createdAt: "2026-10-01",
  ...o,
});

const log = (date: string, o: Partial<DailyLog> = {}): DailyLog => ({
  date,
  goalId: "g1",
  minutes: 30,
  kind: "output",
  difficulty: 3,
  maintainDone: null,
  blocker: "没有",
  win: "",
  ...o,
});

describe("validateGoal", () => {
  it("accepts a complete goal", () => expect(validateGoal(draft(), "2026-10-05")).toEqual([]));
  it("rejects missing outcome, measure and deadline", () => {
    const errs = validateGoal(draft({ outcome: "", measure: "", deadline: "" }), "2026-10-05");
    expect(errs).toHaveLength(3);
  });
  it("rejects past deadline", () =>
    expect(validateGoal(draft({ deadline: "2026-01-01" }), "2026-10-05")).toHaveLength(1));
  it("requires a dose for maintain goals", () =>
    expect(validateGoal(draft({ role: "maintain", dose: "" }), "2026-10-05")).toHaveLength(1));
});

describe("admissionBlock", () => {
  it("blocks a second main goal", () => {
    expect(admissionBlock([goal()], "main")).not.toBeNull();
    expect(admissionBlock([goal()], "main", "g1")).toBeNull();
  });
  it("blocks a fourth maintain goal", () => {
    const gs = [1, 2, 3].map((i) => goal({ id: `m${i}`, role: "maintain" }));
    expect(admissionBlock(gs, "maintain")).not.toBeNull();
    expect(admissionBlock(gs, "paused")).toBeNull();
  });
});

describe("buildWeeklyReview", () => {
  it("returns null without a main goal", () =>
    expect(buildWeeklyReview({ version: 1, goals: [], logs: [] }, "2026-10-05")).toBeNull());

  it("computes completion, top blocker and a single adjustment", () => {
    const logs = [
      log("2026-10-01", { blocker: "太累", minutes: 40 }),
      log("2026-10-03", { blocker: "太累", minutes: 40 }),
      log("2026-10-04", { blocker: "被打断", minutes: 40, win: "完成首次对话" }),
    ];
    const r = buildWeeklyReview({ version: 1, goals: [goal()], logs }, "2026-10-05")!;
    expect(r.doneMinutes).toBe(120);
    expect(r.completion).toBe(67);
    expect(r.topBlocker).toEqual({ blocker: "太累", count: 2 });
    expect(r.adjustment).toContain("太累");
    expect(r.highlight).toBe("完成首次对话");
    expect(r.prevCompletion).toBeNull();
  });
});

describe("forecastDate", () => {
  it("flags a forecast later than the deadline", () => {
    const g = goal({ estimateHours: 600, deadline: "2026-12-31" });
    const f = forecastDate(g, [log("2026-10-04")], "2026-10-05")!;
    expect(f.late).toBe(true);
  });
  it("is null without estimate or input", () => {
    expect(forecastDate(goal(), [log("2026-10-04")], "2026-10-05")).toBeNull();
    expect(forecastDate(goal({ estimateHours: 10 }), [], "2026-10-05")).toBeNull();
  });
});

describe("missedTwoDays", () => {
  it("does not nag after a single missed day", () =>
    expect(missedTwoDays([log("2026-10-03")], "2026-10-05")).toBe(false));
  it("nags after two missed days", () =>
    expect(missedTwoDays([log("2026-10-01")], "2026-10-05")).toBe(true));
});

describe("parseGrowth", () => {
  it("falls back on corrupt data", () => {
    expect(parseGrowth("{bad").goals).toEqual([]);
    expect(parseGrowth(JSON.stringify({ version: 2 })).logs).toEqual([]);
  });
});
