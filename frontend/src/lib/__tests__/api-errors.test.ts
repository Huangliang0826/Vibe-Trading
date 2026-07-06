import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";


describe("API response errors", () => {
  afterEach(() => vi.restoreAllMocks());

  it("replaces an HTML fallback with an actionable health message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "<!doctype html><html><title>Alpha Mind</title></html>",
    } as Response);

    const request = api.getMarketIndices();

    await expect(request).rejects.toEqual(expect.objectContaining({
      name: "ApiError",
      message: "后端 API 未连接，请运行 scripts/dev doctor 检查服务。",
    }));
  });

  it("keeps a concise non-HTML parsing error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "not-json",
    } as Response);

    await expect(api.getMarketIndices()).rejects.toBeInstanceOf(ApiError);
    await expect(api.getMarketIndices()).rejects.toThrow("API returned a non-JSON response: not-json");
  });
});
