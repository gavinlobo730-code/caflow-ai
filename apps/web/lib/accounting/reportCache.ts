/**
 * Cache for accounting report responses, now a thin user of `lib/cache/readCache.ts` (POST-A-124: one store, not two).
 *
 * A report's response is cached keyed by client | financial-year | basis | report with a short TTL: rapid tab switches and revisits within the window are
 * instant and make NO backend call, while staleness is bounded. The cache is cleared explicitly after any local posting (opening balances, journals) so
 * the user's own changes are reflected immediately — never sacrificing correctness. Single-flight (apex-accounting-reports-12) is the shared store's.
 */
import { forgetReads, peekRead, readKey, singleFlight, storeRead } from "../cache/readCache.ts";

const TTL_MS = 60_000;

export const reportKey = readKey;

/** Return the cached response if present, with a flag for whether it's still fresh. */
export function getReport(key: string): { data: unknown; fresh: boolean } | undefined {
  const e = peekRead(key);
  if (!e) return undefined;
  return { data: e.data, fresh: Date.now() - e.readAt < TTL_MS };
}

export function setReport(key: string, data: unknown): void {
  storeRead(key, data);
}

/**
 * Fetch-through cache: returns a fresh cached value without calling the backend; otherwise runs `fetcher`, stores, and returns it. Pass `force: true`
 * (the refresh button) to always re-run `fetcher` and overwrite the cache, even within the TTL window.
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
  return singleFlight(key, fetcher);
}

/** Invalidate cached reports — all, or just one client's — after a local mutation. */
export function clearReports(clientId?: string): void {
  forgetReads(clientId);
}
