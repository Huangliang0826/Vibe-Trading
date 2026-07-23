import { describe, it, expect } from "vitest";
import {
  emptyProgress,
  parseProgress,
  markRead,
  toggleFavorite,
  recordQuizResult,
  BOX_INTERVAL_MS,
  dayKey,
} from "../progress";

describe("parseProgress", () => {
  it("returns empty progress for null / garbage / wrong version", () => {
    expect(parseProgress(null)).toEqual(emptyProgress());
    expect(parseProgress("not json")).toEqual(emptyProgress());
    expect(parseProgress(JSON.stringify({ version: 99 }))).toEqual(emptyProgress());
  });

  it("defaults missing fields without throwing (forward-compatible)", () => {
    const p = parseProgress(JSON.stringify({ version: 1, read: { a: 1 } }));
    expect(p.read).toEqual({ a: 1 });
    expect(p.favorites).toEqual([]);
    expect(p.quiz).toEqual({});
    expect(p.activity).toEqual({});
  });

  it("filters non-string favorites", () => {
    const p = parseProgress(JSON.stringify({ version: 1, favorites: ["a", 2, null, "b"] }));
    expect(p.favorites).toEqual(["a", "b"]);
  });
});

describe("markRead", () => {
  it("records timestamp once and bumps activity", () => {
    const now = Date.UTC(2026, 6, 22, 10);
    const p = markRead(emptyProgress(), "card-1", now);
    expect(p.read["card-1"]).toBe(now);
    expect(p.activity[dayKey(now)]).toBe(1);
  });

  it("is idempotent — re-reading does not overwrite or double-count", () => {
    const now = Date.UTC(2026, 6, 22, 10);
    const p1 = markRead(emptyProgress(), "card-1", now);
    const p2 = markRead(p1, "card-1", now + 5000);
    expect(p2).toBe(p1); // same reference, no change
    expect(p2.read["card-1"]).toBe(now);
  });
});

describe("toggleFavorite", () => {
  it("adds then removes", () => {
    const p1 = toggleFavorite(emptyProgress(), "c");
    expect(p1.favorites).toEqual(["c"]);
    const p2 = toggleFavorite(p1, "c");
    expect(p2.favorites).toEqual([]);
  });
});

describe("recordQuizResult (Leitner)", () => {
  const now = Date.UTC(2026, 6, 22, 10);

  it("correct + confident promotes the box and lengthens the interval", () => {
    const p = recordQuizResult(emptyProgress(), "c", true, true, now);
    expect(p.quiz["c"].box).toBe(2);
    expect(p.quiz["c"].correct).toBe(1);
    expect(p.quiz["c"].due).toBe(now + BOX_INTERVAL_MS[2]);
  });

  it("correct but not confident keeps the box (guessing != mastery)", () => {
    const p = recordQuizResult(emptyProgress(), "c", true, false, now);
    expect(p.quiz["c"].box).toBe(1);
    expect(p.quiz["c"].correct).toBe(1);
  });

  it("wrong answer demotes back to box 1", () => {
    let p = recordQuizResult(emptyProgress(), "c", true, true, now); // box 2
    p = recordQuizResult(p, "c", true, true, now); // box 3
    expect(p.quiz["c"].box).toBe(3);
    p = recordQuizResult(p, "c", false, true, now); // wrong -> box 1
    expect(p.quiz["c"].box).toBe(1);
    expect(p.quiz["c"].wrong).toBe(1);
    expect(p.quiz["c"].due).toBe(now + BOX_INTERVAL_MS[1]);
  });

  it("box never exceeds 3", () => {
    let p = emptyProgress();
    for (let i = 0; i < 5; i++) p = recordQuizResult(p, "c", true, true, now);
    expect(p.quiz["c"].box).toBe(3);
  });
});
