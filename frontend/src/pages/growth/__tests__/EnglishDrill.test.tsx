import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const markEnglishStudied = vi.fn();
const getEnglish = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: {
    getEnglish: (...args: unknown[]) => getEnglish(...args),
    markEnglishStudied: (...args: unknown[]) => markEnglishStudied(...args),
    getEnglishPatterns: vi.fn().mockResolvedValue({ groups: [], levels: [], patterns: [] }),
  },
}));

import { EnglishDrill } from "../EnglishDrill";

const pattern = (id: string, status: "new" | "review") => ({
  id,
  frame: `frame ${id}`,
  group: "A",
  group_label: "缓和与委婉",
  level: "core",
  level_label: "基础",
  meaning: `释义 ${id}`,
  cue: `情境 ${id}`,
  examples: [`example one ${id}`, `example two ${id}`],
  status,
  box: 0,
  seen: 0,
});

const state = (overrides = {}) => ({
  today: "2026-10-06",
  session: [pattern("a", "new"), pattern("b", "new")],
  stats: {
    total: 200, started: 0, tested: 0, accuracy: null,
    automatic: 0, due_today: 0, reviewed_today: 0, box_counts: {},
  },
  shaky: [],
  fast_ms: 6000,
  new_per_day: null,
  session_limit: null,
  groups: [],
  levels: [{ key: "core", label: "基础", total: 100 }],
  ...overrides,
});

beforeEach(() => {
  markEnglishStudied.mockReset();
  markEnglishStudied.mockImplementation(() => Promise.resolve(state({
    stats: { ...state().stats, started: 1 },
  })));
  getEnglish.mockReset();
  getEnglish.mockResolvedValue(state());
});

describe("学习页记录接触", () => {
  it("新句型一显示就记为学过", async () => {
    // 回归:之前只在点「看答案」时上报,而新句型一上来就是展开的,那个按钮
    // 根本不渲染——没练过的句型状态全是 new,等于一条都记不上。
    render(<EnglishDrill />);

    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("a"));
  });

  it("翻到下一条时记录下一条", async () => {
    render(<EnglishDrill />);
    await screen.findByText("frame a");

    await userEvent.click(screen.getByRole("button", { name: /下一条/ }));

    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("b"));
  });

  it("同一张卡不会重复上报", async () => {
    render(<EnglishDrill />);
    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("a"));

    const calls = markEnglishStudied.mock.calls.filter(([id]) => id === "a").length;
    expect(calls).toBe(1);
  });

  it("用返回的统计刷新计数,不必重新加载页面", async () => {
    render(<EnglishDrill />);

    // "学过" 的数字来自每次上报的响应。
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
  });
});
