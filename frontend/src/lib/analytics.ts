import { authHeaders, getApiAuthKey } from "@/lib/apiAuth";
import { APP_VERSION } from "@/lib/version";

type AnalyticsOutcome = "success" | "failure" | "cancelled" | "unknown";
type ProductMetadata = {
  route?: string;
  market?: string;
  result_count?: number;
  source?: string;
  mode?: string;
};

export interface ProductEventInput {
  feature: string;
  action: string;
  outcome: AnalyticsOutcome;
  sessionId?: string;
  durationMs?: number;
  metadata?: ProductMetadata;
}

interface WireEvent {
  event_id: string;
  kind: "product";
  occurred_at: string;
  workspace_id: "local";
  user_id: string;
  session_id?: string;
  feature: string;
  action: string;
  outcome: AnalyticsOutcome;
  duration_ms?: number;
  metadata: ProductMetadata;
  app_version: string;
}

const USER_KEY = "alpha-mind-analytics-user";
const BATCH_URL = "/api/analytics/events";
const MAX_BATCH = 25;
const FLUSH_DELAY_MS = 5_000;

let queue: WireEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function localUserId(): string {
  const existing = localStorage.getItem(USER_KEY);
  if (existing) return existing;
  const created = randomId();
  localStorage.setItem(USER_KEY, created);
  return created;
}

export function analyticsSessionId(route: string): string {
  const key = `alpha-mind-analytics-session:${route}`;
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const created = randomId();
  sessionStorage.setItem(key, created);
  return created;
}

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flushProductEvents();
  }, FLUSH_DELAY_MS);
}

export function trackProductEvent(input: ProductEventInput): void {
  queue.push({
    event_id: randomId(),
    kind: "product",
    occurred_at: new Date().toISOString(),
    workspace_id: "local",
    user_id: localUserId(),
    session_id: input.sessionId,
    feature: input.feature,
    action: input.action,
    outcome: input.outcome,
    duration_ms: input.durationMs === undefined ? undefined : Math.max(0, Math.round(input.durationMs)),
    metadata: { ...input.metadata },
    app_version: APP_VERSION.replace(/^v/, ""),
  });
  if (queue.length >= MAX_BATCH) {
    void flushProductEvents();
  } else {
    scheduleFlush();
  }
}

export async function flushProductEvents(): Promise<void> {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0) return;
  const batch = queue.splice(0, MAX_BATCH);
  try {
    await fetch(BATCH_URL, {
      method: "POST",
      body: JSON.stringify({ events: batch }),
      headers: { "Content-Type": "application/json", ...authHeaders() },
      keepalive: true,
    });
  } catch {
    // Best effort by design: a failed batch is never retried.
  }
  if (queue.length > 0) scheduleFlush();
}

function flushWithBeacon(): void {
  if (queue.length === 0 || getApiAuthKey() || typeof navigator.sendBeacon !== "function") {
    void flushProductEvents();
    return;
  }
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  const batch = queue.splice(0, MAX_BATCH);
  const body = new Blob([JSON.stringify({ events: batch })], { type: "application/json" });
  navigator.sendBeacon(BATCH_URL, body);
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushWithBeacon);
}
