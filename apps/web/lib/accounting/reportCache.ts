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
 * otherwise runs `fetcher`, stores, and returns it.
 */
export async function cachedReport(key: string, fetcher: () => Promise<unknown>): Promise<unknown> {
  const hit = getReport(key);
  if (hit && hit.fresh) return hit.data;
  const data = await fetcher();
  setReport(key, data);
  return data;
}

/** Invalidate cached reports — all, or just one client's — after a local mutation. */
export function clearReports(clientId?: string): void {
  if (!clientId) { cache.clear(); return; }
  const prefix = clientId + "|";
  for (const k of Array.from(cache.keys())) {
    if (k.startsWith(prefix)) cache.delete(k);
  }
}
