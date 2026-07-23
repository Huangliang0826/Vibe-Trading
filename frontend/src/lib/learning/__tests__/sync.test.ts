import { describe, it, expect } from "vitest";
import { mergeProgress, mergeExtra } from "../sync";
import { emptyProgress, type LearningProgress } from "../progress";
import type { ExtraByTopic } from "../extra-store";
import type { KnowledgeCard } from "../types";

function prog(over: Partial<LearningProgress>): LearningProgress {
  return { ...emptyProgress(), ...over };
}

describe("mergeProgress", () => {
  it("unions read keeping the earliest timestamp", () => {
    const a = prog({ read: { x: 100, y: 5 } });
    const b = prog({ read: { x: 50, z: 9 } });
    const m = mergeProgress(a, b);
    expect(m.read).toEqual({ x: 50, y: 5, z: 9 });
  });

  it("unions favorites", () => {
    const m = mergeProgress(prog({ favorites: ["a", "b"] }), prog({ favorites: ["b", "c"] }));
    expect(new Set(m.favorites)).toEqual(new Set(["a", "b", "c"]));
  });

  it("keeps the quiz stat with the later lastAt", () => {
    const a = prog({ quiz: { c: { box: 1, due: 0, correct: 1, wrong: 2, lastAt: 100 } } });
    const b = prog({ quiz: { c: { box: 3, due: 0, correct: 5, wrong: 0, lastAt: 200 } } });
    expect(mergeProgress(a, b).quiz.c.box).toBe(3); // b is newer
    expect(mergeProgress(b, a).quiz.c.box).toBe(3); // order-independent
  });

  it("takes the per-day max activity", () => {
    const m = mergeProgress(prog({ activity: { "2026-07-23": 5 } }), prog({ activity: { "2026-07-23": 2, "2026-07-22": 3 } }));
    expect(m.activity).toEqual({ "2026-07-23": 5, "2026-07-22": 3 });
  });
});

describe("mergeExtra", () => {
  const card = (id: string): KnowledgeCard => ({
    id, topicId: "risk", type: "concept", difficulty: 2, title: id, core: "c", aiGenerated: true,
    quiz: { type: "choice", question: "q", options: ["a", "b"], answer: 0, explanation: "e" },
  });

  it("dedupes by id and sorts by id (chronological via timestamped ids)", () => {
    const a: ExtraByTopic = { risk: [card("risk-ai-2-0"), card("risk-ai-1-0")] };
    const b: ExtraByTopic = { risk: [card("risk-ai-1-0"), card("risk-ai-3-0")] };
    const m = mergeExtra(a, b);
    expect(m.risk!.map((c) => c.id)).toEqual(["risk-ai-1-0", "risk-ai-2-0", "risk-ai-3-0"]);
  });

  it("keeps topics present on only one side", () => {
    const m = mergeExtra({ risk: [card("risk-ai-1-0")] }, { market: [card("market-ai-1-0")] });
    expect(m.risk).toHaveLength(1);
    expect(m.market).toHaveLength(1);
  });
});
