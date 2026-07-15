import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getNewsCenterDates: vi.fn(), getNewsCenterArticles: vi.fn(),
  getNewsCenterDigest: vi.fn(), refreshNewsCenter: vi.fn(), generateNewsAiDigest: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<object>()), api: apiMock }));

import { NewsCenter } from "../NewsCenter";

const TODAY = new Date().toISOString().slice(0, 10);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  // Mark today as already auto-refreshed so the digest-render tests don't
  // trigger the first-open auto-refresh (covered by its own test below).
  localStorage.setItem("news-auto-refresh", TODAY);
  apiMock.refreshNewsCenter.mockResolvedValue({ fetched: 0, total: 1, latest_date: "2026-07-01" });
  apiMock.getNewsCenterDates.mockResolvedValue(["2026-07-01"]);
  apiMock.getNewsCenterArticles.mockResolvedValue({
    items: [{
      article_id: "a1", source: "Tech", title: "腾讯发布新模型",
      url: "https://example.com", published_at: "2026-07-01T09:00:00Z",
      summary: "能力提升", sector: "ai", importance: 100, major: true,
      matches: [{ market: "hk", code: "0700", match_level: "direct", confidence: 90, direction: "positive", strength: 85 }],
    }], total: 1, sectors: ["ai"],
  });
  apiMock.getNewsCenterDigest.mockResolvedValue({
    date: "2026-07-01", article_count: 1, watchlist_count: 1,
    positive_count: 1, negative_count: 0, summary: "今日重点关注腾讯。", major_items: [],
  });
  apiMock.generateNewsAiDigest.mockResolvedValue({
    date: TODAY, article_count: 1, watchlist_count: 1,
    positive_count: 1, negative_count: 0, summary: "模板摘要", major_items: [],
    ai_summary: null, ai_major: [], ai_source: null, ai_enriching: true,
  });
});

it("renders the daily digest and traceable news article", async () => {
  render(<NewsCenter />);
  expect(await screen.findByText("今日重点关注腾讯。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "腾讯发布新模型" })).toHaveAttribute(
    "href", "https://example.com",
  );
  expect(screen.getByText("0700")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "中文新闻" })).toHaveAttribute("aria-selected", "true");
  expect(apiMock.getNewsCenterArticles).toHaveBeenCalledWith(expect.objectContaining({ language: "zh" }));
  expect(apiMock.getNewsCenterDigest).toHaveBeenCalledWith("2026-07-01", "zh");
});

it("auto-refreshes on first daily open when today's news is missing", async () => {
  localStorage.clear(); // no marker → first open today
  render(<NewsCenter />);

  await waitFor(() => expect(apiMock.refreshNewsCenter).toHaveBeenCalled());
  expect(localStorage.getItem("news-auto-refresh")).toBe(TODAY);
});

it("does not auto-refresh when today's news already exists", async () => {
  localStorage.clear();
  apiMock.getNewsCenterDates.mockResolvedValue([TODAY]); // latest == today, not stale
  apiMock.getNewsCenterDigest.mockResolvedValue({
    date: TODAY, article_count: 1, watchlist_count: 0,
    positive_count: 0, negative_count: 0, summary: "今日无重点。", major_items: [],
  });
  render(<NewsCenter />);

  await screen.findByText("模板摘要");
  expect(apiMock.refreshNewsCenter).not.toHaveBeenCalled();
});

it("returns the local digest while background web generation runs", async () => {
  apiMock.getNewsCenterDates.mockResolvedValue([TODAY]);
  apiMock.getNewsCenterDigest.mockResolvedValue({
    date: TODAY, article_count: 1, watchlist_count: 0,
    positive_count: 0, negative_count: 0, summary: "模板摘要", major_items: [],
  });
  render(<NewsCenter />);

  expect(await screen.findByText("模板摘要")).toBeInTheDocument();
  expect(screen.getByText("正在后台生成 AI 联网总结…")).toBeInTheDocument();
});

it("renders the online investment briefing as three bullet points", async () => {
  apiMock.getNewsCenterDigest.mockResolvedValue({
    date: "2026-07-01", article_count: 1, watchlist_count: 0,
    positive_count: 0, negative_count: 0, summary: "模板摘要", major_items: [],
    ai_summary: "地缘政治：地区局势变化\n金融：市场利率变化\n科技：新模型发布",
    ai_source: "web", ai_enriching: false,
  });

  render(<NewsCenter />);

  expect(await screen.findByText("地缘政治：")).toBeInTheDocument();
  expect(screen.getByText("金融：")).toBeInTheDocument();
  expect(screen.getByText("科技：")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
});

it("switches the article list and digest to English", async () => {
  render(<NewsCenter />);
  await screen.findByText("今日重点关注腾讯。");

  await userEvent.click(screen.getByRole("tab", { name: "英文新闻" }));

  await waitFor(() => expect(apiMock.getNewsCenterArticles).toHaveBeenLastCalledWith(
    expect.objectContaining({ language: "en" }),
  ));
  expect(apiMock.getNewsCenterDigest).toHaveBeenLastCalledWith("2026-07-01", "en");
});
