"use client";

/**
 * Session-scoped cache for HSN/SAC lookups (HSN/SAC UX performance
 * refinement). Repeated/backspace-then-retyped HSN searches (very common
 * while drafting a line) re-hit the network for a query already answered
 * this session. Successful results are cached by exact query string so a
 * repeat is instant; failures are NOT cached, so retry() genuinely retries
 * instead of replaying the same rejection forever.
 *
 * The catalogue-fetch cache that used to live here (getCachedCatalogue /
 * recordCatalogueUsed, for the legacy LineItemAutocomplete description
 * type-ahead) was removed with that component (Final Invoice Workflow
 * Alignment): the invoice is now Product/Service-driven via
 * ServiceCataloguePicker, which fetches directly — no shared client-side
 * cache needed for a deliberate, one-at-a-time "+ Add Product/Service" pick.
 */
import { api, type ApiResp } from "@/lib/api";
import type { HsnRow } from "@/lib/lookups/hsn";

const hsnRecentCache = new Map<string, Promise<HsnRow[]>>();

/** The client's recent HSN/SAC history, deduped per (clientId, type) across
 * every row that wants it (every HsnLookup "Change" chip on the page shares
 * this instead of each firing its own request).
 *
 * Rejects (rather than resolving with []) on any failure — a caught
 * app-level error (success:false, still HTTP 200) or a network exception —
 * and evicts the cache entry either way so a caller's retry genuinely
 * re-fetches instead of replaying a stale failure forever. A silent []
 * here would be indistinguishable from "this client has no history yet",
 * which is a false negative for something that actually exists and simply
 * failed to load (most visible on a cold backend start). */
export function getCachedHsnRecent(clientId: string, type?: string): Promise<HsnRow[]> {
  if (!clientId) return Promise.resolve([]);
  const key = `${clientId}::${type ?? ""}`;
  if (!hsnRecentCache.has(key)) {
    hsnRecentCache.set(
      key,
      (api.hsn.search("", { client_id: clientId, type, limit: 8 }) as Promise<ApiResp<HsnRow[]>>)
        .then((res) => {
          if (!res.success) throw new Error(res.error ?? "Couldn't load recent HSN/SAC codes");
          return res.data ?? [];
        })
        .catch((e) => {
          hsnRecentCache.delete(key);
          throw e;
        }),
    );
  }
  return hsnRecentCache.get(key)!;
}

const hsnQueryCache = new Map<string, Promise<HsnRow[]>>();

/** A typed HSN/SAC search, cached by exact (query, clientId, type) for the
 * rest of the session — a repeat or backspace-then-retyped query resolves
 * instantly instead of re-hitting the network. Only successes are cached;
 * a failed request is evicted so retry() issues a genuinely fresh attempt. */
export function getCachedHsnSearch(query: string, clientId?: string, type?: string): Promise<HsnRow[]> {
  const key = `${clientId ?? ""}::${type ?? ""}::${query.trim().toLowerCase()}`;
  if (!hsnQueryCache.has(key)) {
    hsnQueryCache.set(
      key,
      (api.hsn.search(query, { client_id: clientId, type, limit: 8 }) as Promise<ApiResp<HsnRow[]>>)
        .then((res) => {
          if (!res.success) throw new Error(res.error ?? "Couldn't search HSN/SAC");
          return res.data ?? [];
        })
        .catch((e) => {
          hsnQueryCache.delete(key);
          throw e;
        }),
    );
  }
  return hsnQueryCache.get(key)!;
}
