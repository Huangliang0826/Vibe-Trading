import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getNewsCenterDates: vi.fn(), getNewsCenterArticles: vi.fn(),
  getNewsCenterDigest: vi.fn(), refreshNewsCenter: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<object>()), api: apiMock }));

import { NewsCenter } from "../NewsCenter";

beforeEach(() => {
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

it("switches the article list and digest to English", async () => {
  render(<NewsCenter />);
  await screen.findByText("今日重点关注腾讯。");

  await userEvent.click(screen.getByRole("tab", { name: "英文新闻" }));

  await waitFor(() => expect(apiMock.getNewsCenterArticles).toHaveBeenLastCalledWith(
    expect.objectContaining({ language: "en" }),
  ));
  expect(apiMock.getNewsCenterDigest).toHaveBeenLastCalledWith("2026-07-01", "en");
});
