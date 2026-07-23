import { describe, it, expect } from "vitest";
import { currentStreak, activityHeatmap, isMastered, overallStats } from "../stats";
import { emptyProgress, dayKey, type LearningProgress } from "../progress";
import { ALL_CARDS } from "../content";
import type { KnowledgeCard } from "../types";

const DAY = 24 * 60 * 60 * 1000;

describe("currentStreak", () => {
  const now = Date.UTC(2026, 6, 22, 10);

  it("is 0 with no activity", () => {
    expect(currentStreak({}, now)).toBe(0);
  });

  it("counts consecutive days including today", () => {
    const activity = {
      [dayKey(now)]: 1,
      [dayKey(now - DAY)]: 2,
      [dayKey(now - 2 * DAY)]: 1,
    };
    expect(currentStreak(activity, now)).toBe(3);
  });

  it("still counts if today is missing but yesterday is present", () => {
    const activity = { [dayKey(now - DAY)]: 1, [dayKey(now - 2 * DAY)]: 1 };
    expect(currentStreak(activity, now)).toBe(2);
  });

  it("breaks on a gap", () => {
    const activity = { [dayKey(now)]: 1, [dayKey(now - 2 * DAY)]: 1 };
    expect(currentStreak(activity, now)).toBe(1);
  });
});

describe("activityHeatmap", () => {
  const now = Date.UTC(2026, 6, 22, 10);
  it("returns the requested number of days ending today, chronologically", () => {
    const cells = activityHeatmap({ [dayKey(now)]: 4 }, 30, now);
    expect(cells).toHaveLength(30);
    expect(cells[cells.length - 1].date).toBe(dayKey(now));
    expect(cells[cells.length - 1].count).toBe(4);
    expect(cells[0].count).toBe(0);
  });
});

describe("isMastered", () => {
  const now = Date.UTC(2026, 6, 22, 10);
  it("is true only when box >= 2", () => {
    const p: LearningProgress = {
      ...emptyProgress(),
      quiz: {
        a: { box: 1, due: now, correct: 1, wrong: 0, lastAt: now },
        b: { box: 2, due: now, correct: 1, wrong: 0, lastAt: now },
      },
    };
    expect(isMastered(p, "a")).toBe(false);
    expect(isMastered(p, "b")).toBe(true);
    expect(isMastered(p, "missing")).toBe(false);
  });
});

describe("content integrity", () => {
  it("has exactly 100 cards across 5 topics", () => {
    expect(ALL_CARDS.length).toBe(100);
  });

  it("every card has a well-formed quiz with a valid answer index", () => {
    for (const c of ALL_CARDS as KnowledgeCard[]) {
      expect(c.quiz.options.length).toBeGreaterThanOrEqual(2);
      expect(c.quiz.answer).toBeGreaterThanOrEqual(0);
      expect(c.quiz.answer).toBeLessThan(c.quiz.options.length);
      expect(c.quiz.explanation.length).toBeGreaterThan(0);
    }
  });

  it("card ids are unique", () => {
    const ids = ALL_CARDS.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("overallStats reflects reads and mastery on real content", () => {
    const first = ALL_CARDS[0];
    const now = Date.UTC(2026, 6, 22, 10);
    const p: LearningProgress = {
      ...emptyProgress(),
      read: { [first.id]: now },
      quiz: { [first.id]: { box: 2, due: now + DAY, correct: 1, wrong: 0, lastAt: now } },
    };
    const s = overallStats(p, ALL_CARDS, now);
    expect(s.totalCards).toBe(100);
    expect(s.totalRead).toBe(1);
    expect(s.totalMastered).toBe(1);
    expect(s.accuracy).toBe(100);
  });
});
