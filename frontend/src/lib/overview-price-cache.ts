const PREFIX = "vibe:overview-market-metrics-v1:";

type CacheEnvelope<T> = { savedAt: number; value: T };

export function historyCacheKey(market: string, code: string, period: string): string {
  return `history:${market}:${code.toUpperCase()}:${period.toUpperCase()}`;
}

export function quoteCacheKey(market: string, code: string): string {
  return `quote:${market}:${code.toUpperCase()}`;
}

export function readOverviewCache<T>(
  key: string,
  ttlMs: number,
  now = Date.now(),
): { value: T; isFresh: boolean } | null {
  try {
    const raw = localStorage.getItem(`${PREFIX}${key}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<T>;
    if (!Number.isFinite(parsed.savedAt) || parsed.value == null) return null;
    return { value: parsed.value, isFresh: now - parsed.savedAt <= ttlMs };
  } catch {
    return null;
  }
}

export function writeOverviewCache<T>(key: string, value: T, now = Date.now()): void {
  try {
    localStorage.setItem(`${PREFIX}${key}`, JSON.stringify({ savedAt: now, value }));
  } catch {
    // Storage is best-effort; network loading remains the fallback.
  }
}
