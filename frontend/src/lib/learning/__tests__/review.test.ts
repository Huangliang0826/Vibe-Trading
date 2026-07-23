import { describe, it, expect } from "vitest";
import { buildReviewQueue, countDueReviews, shuffledOptions } from "../review";
import { emptyProgress, type LearningProgress } from "../progress";
import type { KnowledgeCard } from "../types";

function card(id: string, topicId: KnowledgeCard["topicId"] = "market"): KnowledgeCard {
  return {
    id,
    topicId,
    type: "concept",
    difficulty: 1,
    title: id,
    core: "core",
    quiz: { type: "choice", question: "q", options: ["a", "b", "c", "d"], answer: 2, explanation: "e" },
  };
}

const DAY = 24 * 60 * 60 * 1000;

describe("buildReviewQueue", () => {
  const now = Date.UTC(2026, 6, 22, 10);
  const cards = [card("a"), card("b"), card("c"), card("d")];

  it("only includes cards that have been read", () => {
    const p: LearningProgress = { ...emptyProgress(), read: { a: now, b: now } };
    const q = buildReviewQueue(p, cards, "all", now);
    expect(q.map((i) => i.card.id).sort()).toEqual(["a", "b"]);
    // never-quizzed read cards are "fresh" (not due)
    expect(q.every((i) => i.due === false)).toBe(true);
  });

  it("excludes not-yet-due answered cards", () => {
    const p: LearningProgress = {
      ...emptyProgress(),
      read: { a: now },
      quiz: { a: { box: 2, due: now + 3 * DAY, correct: 1, wrong: 0, lastAt: now } },
    };
    expect(buildReviewQueue(p, cards, "all", now)).toHaveLength(0);
  });

  it("prioritizes due cards with lower box and more wrongs first", () => {
    const p: LearningProgress = {
      ...emptyProgress(),
      read: { a: now, b: now, c: now },
      quiz: {
        a: { box: 3, due: now - DAY, correct: 5, wrong: 0, lastAt: now }, // high box, mastered
        b: { box: 1, due: now - DAY, correct: 0, wrong: 3, lastAt: now }, // low box, error-prone
      },
    };
    const q = buildReviewQueue(p, cards, "all", now);
    // b (low box, many wrongs) should come before a; c is fresh, comes last
    expect(q[0].card.id).toBe("b");
    expect(q[q.length - 1].card.id).toBe("c");
    expect(q[q.length - 1].due).toBe(false);
  });

  it("respects topic filtering", () => {
    const mixed = [card("a", "market"), card("x", "risk")];
    const p: LearningProgress = { ...emptyProgress(), read: { a: now, x: now } };
    const q = buildReviewQueue(p, mixed, "risk", now);
    expect(q.map((i) => i.card.id)).toEqual(["x"]);
  });
});

describe("countDueReviews", () => {
  const now = Date.UTC(2026, 6, 22, 10);
  it("counts only read + due cards", () => {
    const p: LearningProgress = {
      ...emptyProgress(),
      read: { a: now, b: now },
      quiz: {
        a: { box: 1, due: now - DAY, correct: 0, wrong: 1, lastAt: now }, // due
        b: { box: 2, due: now + DAY, correct: 1, wrong: 0, lastAt: now }, // not due
      },
    };
    expect(countDueReviews(p, [card("a"), card("b")], now)).toBe(1);
  });
});

describe("shuffledOptions", () => {
  it("preserves the correct answer text and is deterministic per card id", () => {
    const c = card("stable-id");
    const r1 = shuffledOptions(c);
    const r2 = shuffledOptions(c);
    expect(r1).toEqual(r2); // deterministic
    expect(r1.options).toHaveLength(4);
    expect(new Set(r1.options)).toEqual(new Set(c.quiz.options));
    // the option at the new answer index equals the original correct option
    expect(r1.options[r1.answer]).toBe(c.quiz.options[c.quiz.answer]);
  });
});
