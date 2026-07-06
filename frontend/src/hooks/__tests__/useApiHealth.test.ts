import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useApiHealth } from "../useApiHealth";


function response(body: string, contentType: string, ok = true): Response {
  return {
    ok,
    headers: new Headers({ "content-type": contentType }),
    json: async () => JSON.parse(body),
  } as Response;
}


describe("useApiHealth", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("accepts the backend healthy JSON contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response('{"status":"healthy"}', "application/json"),
    );

    const { result } = renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.status).toBe("healthy"));
    expect(fetch).toHaveBeenCalledWith("/health", expect.objectContaining({ cache: "no-store" }));
  });

  it("classifies an HTML fallback as a proxy misconfiguration", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response("<!doctype html>", "text/html"),
    );

    const { result } = renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.status).toBe("misconfigured"));
  });

  it("classifies a network failure as unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("exposes a manual retry", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(response('{"status":"healthy"}', "application/json"));
    const { result } = renderHook(() => useApiHealth());
    await waitFor(() => expect(result.current.status).toBe("unavailable"));

    await act(async () => result.current.retry());

    await waitFor(() => expect(result.current.status).toBe("healthy"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("checks again after fifteen seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response('{"status":"healthy"}', "application/json"),
    );
    renderHook(() => useApiHealth());
    await act(async () => Promise.resolve());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
