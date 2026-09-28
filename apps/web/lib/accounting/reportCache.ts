/**
 * Tiny cache for accounting report responses.
 *
 * The accounting reports go through the FastAPI backend (unlike Sales/Customers,
 * which read Supabase directly), so each report pays a network round-trip + a
 * possible cold start. Without caching, every tab switch / revisit re-hits the
 * backend and re-runs the full ledger snapshot.
 *
 * This caches a report's response keyed by client | financial-year | basis |
 * report, with a short TTL: rapid tab switches and revisits within the window are
 * instant and make NO backend call, while staleness is bounded. The cache is
 * cleared explicitly after any local posting (opening balances, journals) so the
 * user's own changes are reflected immediately — never sacrificing correctness.
 */
type Entry = { ts: number; data: unknown };

const cache = new Map<string, Entry>();
const TTL_MS = 60_000;

/**
 * Requests currently in flight, keyed the same way as `cache` (single-flight).
 *
 * apex-accounting-reports-12: the URL/tab-sync remount bug used to fire a
 * mounted tab's own data effect two or three times in a row, and each of
 * those calls missed the settled cache (nothing had resolved yet) and issued
 * its own backend request — so fixing the remount alone still leaves any two
 * genuinely near-simultaneous callers for the same report (e.g. a fast
 * double-click, or two components reading the same key) paying for the
 * ledger snapshot twice. Caching the PROMISE, not only the settled value,
 * means the second caller awaits the first one's request instead of starting
 * its own.
 */
const inFlight = new Map<string, Promise<unknown>>();

export function reportKey(parts: (string | undefined)[]): string {
  return parts.map((p) => p ?? "").join("|");
}

/** Return the cached response if present, with a flag for whether it's still fresh. */
export function getReport(key: string): { data: unknown; fresh: boolean } | undefined {
  const e = cache.get(key);
  if (!e) return undefined;
  return { data: e.data, fresh: Date.now() - e.ts < TTL_MS };
}

export function setReport(key: string, data: unknown): void {
  cache.set(key, { ts: Date.now(), data });
}

/**
 * Fetch-through cache: returns a fresh cached value without calling the backend;
 * otherwise runs `fetcher`, stores, and returns it. Pass `force: true` (the
 * refresh button) to always re-run `fetcher` and overwrite the cache, even
 * within the TTL window.
 */
export async function cachedReport(
  key: string,
  fetcher: () => Promise<unknown>,
  opts?: { force?: boolean },
): Promise<unknown> {
  if (!opts?.force) {
    const hit = getReport(key);
    if (hit && hit.fresh) return hit.data;
  }
  // Single-flight: a second caller for the same key while the first is still
  // outstanding awaits that SAME promise rather than issuing its own request.
  const existing = inFlight.get(key);
  if (existing) return existing;
  const promise = (async () => {
    try {
      const data = await fetcher();
      setReport(key, data);
      return data;
    } finally {
      inFlight.delete(key);
    }
  })();
  inFlight.set(key, promise);
  return promise;
}

/** Invalidate cached reports — all, or just one client's — after a local mutation. */
export function clearReports(clientId?: string): void {
  if (!clientId) { cache.clear(); return; }
  const prefix = clientId + "|";
  for (const k of Array.from(cache.keys())) {
    if (k.startsWith(prefix)) cache.delete(k);
  }
}
