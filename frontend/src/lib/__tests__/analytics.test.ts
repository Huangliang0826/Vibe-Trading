import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushProductEvents, trackProductEvent } from "../analytics";

describe("analytics transport", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("batches allowlisted fields without prompt content", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 202 }));
    trackProductEvent({
      feature: "scanner",
      action: "result_view",
      outcome: "success",
      metadata: { route: "/scanner" },
    });
    await flushProductEvents();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.events).toHaveLength(1);
    expect(JSON.stringify(body)).not.toContain("prompt");
  });
});
