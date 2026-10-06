import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const markEnglishStudied = vi.fn();
const getEnglish = vi.fn();
const setEnglishFavorite = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: {
    getEnglish: (...args: unknown[]) => getEnglish(...args),
    markEnglishStudied: (...args: unknown[]) => markEnglishStudied(...args),
    setEnglishFavorite: (...args: unknown[]) => setEnglishFavorite(...args),
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
  track: "frame",
  track_label: "句型",
  meaning: `释义 ${id}`,
  cue: `情境 ${id}`,
  examples: [`example one ${id}`, `example two ${id}`],
  status,
  box: 0,
  seen: 0,
  favorite: false,
});

const state = (overrides = {}) => ({
  today: "2026-10-06",
  track: "frame",
  tracks: [{ key: "frame", label: "句型", total: 152 }],
  session: [pattern("a", "new"), pattern("b", "new")],
  stats: {
    total: 200, started: 0, tested: 0, accuracy: null, favorites: 0,
    automatic: 0, due_today: 0, reviewed_today: 0, box_counts: {},
  },
  favorites: [],
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
  setEnglishFavorite.mockReset();
  setEnglishFavorite.mockImplementation(() => Promise.resolve(state({
    stats: { ...state().stats, favorites: 1 },
    favorites: [{
      id: "a", frame: "frame a", meaning: "释义 a",
      group_label: "缓和与委婉", level_label: "基础",
    }],
  })));
});

describe("学习页记录接触", () => {
  it("新句型一显示就记为学过", async () => {
    // 回归:之前只在点「看答案」时上报,而新句型一上来就是展开的,那个按钮
    // 根本不渲染——没练过的句型状态全是 new,等于一条都记不上。
    render(<EnglishDrill track="frame" />);

    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("a"));
  });

  it("翻到下一条时记录下一条", async () => {
    render(<EnglishDrill track="frame" />);
    await screen.findByText("frame a");

    await userEvent.click(screen.getByRole("button", { name: /下一句/ }));

    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("b"));
  });

  it("同一张卡不会重复上报", async () => {
    render(<EnglishDrill track="frame" />);
    await waitFor(() => expect(markEnglishStudied).toHaveBeenCalledWith("a"));

    const calls = markEnglishStudied.mock.calls.filter(([id]) => id === "a").length;
    expect(calls).toBe(1);
  });

  it("用返回的统计刷新计数,不必重新加载页面", async () => {
    render(<EnglishDrill track="frame" />);

    // "学过" 的数字来自每次上报的响应。
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
  });
});

describe("收藏与键盘", () => {
  it("收藏按钮把当前句式标记为已收藏", async () => {
    render(<EnglishDrill track="frame" />);
    await screen.findByText("frame a");

    await userEvent.click(screen.getByRole("button", { name: /收藏/ }));

    await waitFor(() => expect(setEnglishFavorite).toHaveBeenCalledWith("a", true));
  });

  it("收藏状态立刻反映在按钮上,不等往返", async () => {
    render(<EnglishDrill track="frame" />);
    await screen.findByText("frame a");

    await userEvent.click(screen.getByRole("button", { name: /收藏/ }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /已收藏/ })).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("按向右键翻到下一句", async () => {
    render(<EnglishDrill track="frame" />);
    await screen.findByText("frame a");

    await userEvent.keyboard("{ArrowRight}");

    expect(await screen.findByText("frame b")).toBeInTheDocument();
  });

  it("在输入框里按向右键只移动光标,不翻页", async () => {
    // 否则下方"全部句型"等处一旦有输入框,打字就会把卡片翻走。
    render(
      <>
        <input aria-label="测试输入" />
        <EnglishDrill track="frame" />
      </>,
    );
    await screen.findByText("frame a");

    await userEvent.click(screen.getByLabelText("测试输入"));
    await userEvent.keyboard("{ArrowRight}");

    expect(screen.getByText("frame a")).toBeInTheDocument();
  });
});

describe("向右键的健壮性", () => {
  it("事件目标不是元素时也不会把快捷键打死", async () => {
    // window / document 上派发的 keydown 其 target 没有 closest;
    // 当成元素直接调用会抛错,整个快捷键就静默失效了。
    render(<EnglishDrill track="frame" />);
    await screen.findByText("frame a");

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));

    expect(await screen.findByText("frame b")).toBeInTheDocument();
  });
});
