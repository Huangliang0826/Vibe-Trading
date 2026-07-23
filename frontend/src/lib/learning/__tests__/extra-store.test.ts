import { describe, it, expect, beforeEach } from "vitest";
import { appendGeneratedCards, loadExtra, EXTRA_KEY, type ExtraByTopic } from "../extra-store";
import type { GeneratedCard } from "@/lib/api";

function genCard(title: string): GeneratedCard {
  return {
    type: "story",
    difficulty: 2,
    title,
    core: "core text",
    example: "an example",
    pitfall: "a pitfall",
    quiz: {
      type: "scenario",
      question: "q?",
      options: ["a", "b", "c", "d"],
      answer: 1,
      explanation: "because b",
      ai_generated: true,
    },
  };
}

describe("appendGeneratedCards", () => {
  beforeEach(() => localStorage.clear());

  it("assigns stable ids, marks aiGenerated, and persists", () => {
    const { next, added } = appendGeneratedCards({}, "risk", [genCard("A"), genCard("B")], 1000);
    expect(added).toHaveLength(2);
    expect(added[0].id).toBe("risk-ai-1000-0");
    expect(added[1].id).toBe("risk-ai-1000-1");
    expect(added[0].topicId).toBe("risk");
    expect(added[0].aiGenerated).toBe(true);
    expect(added[0].quiz.options[added[0].quiz.answer]).toBe("b");
    // persisted to localStorage under the topic
    const stored = JSON.parse(localStorage.getItem(EXTRA_KEY)!) as ExtraByTopic;
    expect(stored.risk).toHaveLength(2);
    expect(next.risk).toHaveLength(2);
  });

  it("appends to existing extras without dropping them", () => {
    const first = appendGeneratedCards({}, "market", [genCard("A")], 1);
    const second = appendGeneratedCards(first.next, "market", [genCard("B")], 2);
    expect(second.next.market).toHaveLength(2);
    expect(second.next.market!.map((c) => c.title)).toEqual(["A", "B"]);
  });

  it("loadExtra round-trips persisted cards and filters malformed entries", () => {
    appendGeneratedCards({}, "quant", [genCard("Keep")], 5);
    // inject a malformed card alongside
    const raw = JSON.parse(localStorage.getItem(EXTRA_KEY)!);
    raw.quant.push({ id: "", title: "", core: "" });
    localStorage.setItem(EXTRA_KEY, JSON.stringify(raw));
    const loaded = loadExtra();
    expect(loaded.quant).toHaveLength(1);
    expect(loaded.quant![0].title).toBe("Keep");
  });

  it("loadExtra returns empty object on missing/garbage storage", () => {
    localStorage.clear();
    expect(loadExtra()).toEqual({});
    localStorage.setItem(EXTRA_KEY, "not json");
    expect(loadExtra()).toEqual({});
  });
});
