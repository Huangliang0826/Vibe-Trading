const PREFIX = "vibe:forecast-session:";

export function forecastSessionKey(market: string, code: string, context: number, displayHistory: number): string {
  return `forecast:${market}:${code.toUpperCase()}:${context}:${displayHistory}`;
}

export function strategySessionKey(market: string, code: string): string {
  // v2: pre-v2 caches stripped `candidates`, which the strategy picker needs.
  return `strategy:v2:${market}:${code.toUpperCase()}`;
}

type CacheEnvelope<T> = { savedAt: number; value: T };

export function readSessionCache<T>(key: string, ttlMs: number, now = Date.now()): T | null {
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${key}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<T>;
    if (!Number.isFinite(parsed.savedAt) || now - parsed.savedAt > ttlMs) {
      sessionStorage.removeItem(`${PREFIX}${key}`);
      return null;
    }
    return parsed.value;
  } catch {
    return null;
  }
}

export function writeSessionCache<T>(key: string, value: T, now = Date.now()): void {
  try {
    sessionStorage.setItem(`${PREFIX}${key}`, JSON.stringify({ savedAt: now, value }));
  } catch {
    // Browser storage is best-effort; the backend remains the source of truth.
  }
}

export function compactStrategyResponse<T extends object>(value: T): T {
  const record = value as Record<string, unknown>;
  const best = (record.best || {}) as Record<string, unknown>;
  const selection = (record.selection || {}) as Record<string, unknown>;
  const { robust_result: _robustResult, ...compactSelection } = selection;
  return {
    ...record,
    // candidates carry only strategy label + summary metrics (no trades /
    // equity), so keep them — the strategy picker renders from this list.
    best: { ...best, equity_curve: [] },
    selection: compactSelection,
  } as T;
}
