const PREFIX = "vibe:overview-price:";
// Hard cap on cached price blobs. Without eviction these (esp. multi-year "ALL"
// histories) accumulate until localStorage hits its quota, after which *any*
// setItem — including the critical watchlist — throws. Keep a bounded working
// set; the backend is always the source of truth.
const MAX_ENTRIES = 80;

type CacheEnvelope<T> = { savedAt: number; value: T };

function overviewCacheKeys(): string[] {
  const keys: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(PREFIX)) keys.push(k);
  }
  return keys;
}

function savedAtOf(fullKey: string): number {
  try {
    return (JSON.parse(localStorage.getItem(fullKey) || "{}") as CacheEnvelope<unknown>).savedAt || 0;
  } catch {
    return 0;
  }
}

/** Evict oldest overview-price entries, keeping the `keep` newest. Returns removed count. */
export function pruneOverviewCache(keep = Math.floor(MAX_ENTRIES / 2)): number {
  const keys = overviewCacheKeys().sort((a, b) => savedAtOf(b) - savedAtOf(a)); // newest first
  const doomed = keys.slice(Math.max(0, keep));
  let removed = 0;
  for (const k of doomed) {
    try { localStorage.removeItem(k); removed += 1; } catch { /* ignore */ }
  }
  return removed;
}

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
  const payload = JSON.stringify({ savedAt: now, value });
  try {
    localStorage.setItem(`${PREFIX}${key}`, payload);
  } catch {
    // Quota hit — evict the oldest entries and retry once.
    try {
      pruneOverviewCache();
      localStorage.setItem(`${PREFIX}${key}`, payload);
    } catch {
      // Still failing (e.g. a single blob larger than the freed space); give up.
      // Network loading remains the fallback.
    }
  }
  // Opportunistic bound so the cache can't grow unbounded even without a throw.
  if (overviewCacheKeys().length > MAX_ENTRIES) pruneOverviewCache();
}
