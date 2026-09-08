import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** The paper-trading strategy catalog is hardcoded in the frontend while the
 *  backend keeps its own list, so a strategy added on one side can silently
 *  fail to appear on the other — which is exactly what happened with
 *  atr_risk_budget. These tests keep the frontend's three places in step. */
const src = readFileSync(resolve(process.cwd(), "src/pages/PaperTrading.tsx"), "utf-8");

const optionValues = [...src.matchAll(/\{ value: "(\w+)"/g)].map((m) => m[1]);
const unionMembers = (() => {
  const block = src.slice(src.indexOf("type StrategyName ="), src.indexOf("const STRATEGY_OPTIONS"));
  return [...block.matchAll(/\| "(\w+)"/g)].map((m) => m[1]);
})();
const principleKeys = (() => {
  const start = src.indexOf("STRATEGY_PRINCIPLES");
  const block = src.slice(start, src.indexOf("\n};", start));
  return [...block.matchAll(/^\s{2}(\w+):\s*"策略原理/gm)].map((m) => m[1]);
})();

describe("paper trading strategy catalog", () => {
  it("lists every StrategyName as a selectable option", () => {
    expect([...unionMembers].sort()).toEqual([...optionValues].sort());
  });

  it("gives every option a 策略原理 description", () => {
    const missing = optionValues.filter((v) => !principleKeys.includes(v));
    expect(missing).toEqual([]);
  });

  it("includes atr_risk_budget", () => {
    // Regression: it was registered backend-side but missing from this list.
    expect(optionValues).toContain("atr_risk_budget");
  });
});
