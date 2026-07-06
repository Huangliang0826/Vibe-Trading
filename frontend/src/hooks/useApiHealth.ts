import { useCallback, useEffect, useRef, useState } from "react";


export type ApiHealthStatus = "checking" | "healthy" | "unavailable" | "misconfigured";

const CHECK_INTERVAL_MS = 15_000;


export function useApiHealth(): { status: ApiHealthStatus; retry: () => Promise<void> } {
  const [status, setStatus] = useState<ApiHealthStatus>("checking");
  const controllerRef = useRef<AbortController | null>(null);

  const retry = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("checking");

    try {
      const response = await fetch("/health", {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        setStatus("unavailable");
        return;
      }
      const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
      if (!contentType.includes("application/json")) {
        setStatus("misconfigured");
        return;
      }
      const payload = await response.json() as { status?: unknown };
      setStatus(payload.status === "healthy" ? "healthy" : "unavailable");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setStatus("unavailable");
      }
    }
  }, []);

  useEffect(() => {
    void retry();
    const interval = window.setInterval(() => void retry(), CHECK_INTERVAL_MS);
    const checkNow = () => void retry();
    window.addEventListener("focus", checkNow);
    window.addEventListener("online", checkNow);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", checkNow);
      window.removeEventListener("online", checkNow);
      controllerRef.current?.abort();
    };
  }, [retry]);

  return { status, retry };
}
