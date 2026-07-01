import { render, screen } from "@testing-library/react";
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
});
