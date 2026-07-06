"use client";

/**
 * Session-scoped caches for the line-item suggestion sources (HSN/SAC UX
 * performance refinement). Two distinct problems, two distinct caches:
 *
 *  1. Every invoice line renders its OWN LineItemAutocomplete (and its own
 *     secondary HsnLookup for the "Change" chip). Before this cache, each
 *     row independently fetched the whole Service Catalogue and the client's
 *     "recent HSN" list on mount — a 10-line invoice fired ~20 redundant,
 *     near-simultaneous requests for data every row wants identically. These
 *     helpers de-duplicate concurrent callers onto ONE in-flight promise and
 *     reuse the resolved value for the rest of the page's lifetime.
 *
 *  2. Repeated/backspace-then-retyped HSN searches (very common while
 *     drafting a line) re-hit the network for a query already answered this
 *     session. Successful results are cached by exact query string so a
 *     repeat is instant; failures are NOT cached, so retry() genuinely
 *     retries instead of replaying the same rejection forever.
 *
 * The Service Catalogue itself is small (a firm's own billing presets, not
 * the HSN master) and firm-scoped, not client-scoped, so ONE fetch (up to
 * 100 items, the API's own cap) covers every line on every invoice for the
 * rest of the session — letting the description field filter it entirely
 * client-side (lib/combobox/match.ts's existing sync engine), with zero
 * network latency per keystroke.
 */
import { api, type ApiResp } from "@/lib/api";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import type { HsnRow } from "@/lib/lookups/hsn";

let catalogueCache: Promise<ServiceCatalogueItem[]> | null = null;

/** The firm's full active catalogue (recent/frequent-first, per the API's own
 * default ordering), fetched once and shared by every line on the page. */
export function getCachedCatalogue(): Promise<ServiceCatalogueItem[]> {
  if (!catalogueCache) {
    catalogueCache = (api.serviceCatalogue.list({ limit: 100 }) as Promise<ApiResp<ServiceCatalogueItem[]>>)
      .then((res) => res.data ?? [])
      .catch(() => {
        catalogueCache = null; // allow a later mount to retry instead of caching a permanent failure
        return [];
      });
  }
  return catalogueCache;
}

/** Bump a catalogue item's usage AND drop the cached list, so the next fetch
 * (e.g. the next line added, or the next invoice opened this session) picks
 * up its updated recency/use-count instead of serving stale ordering. */
export function recordCatalogueUsed(id: string): void {
  api.serviceCatalogue.recordUsed(id).catch(() => {});
  catalogueCache = null;
}

const hsnRecentCache = new Map<string, Promise<HsnRow[]>>();

/** The client's recent HSN/SAC history, deduped per (clientId, type) across
 * every row that wants it (LineItemAutocomplete AND HsnLookup's own recent
 * list both call this now, instead of each firing their own request). */
export function getCachedHsnRecent(clientId: string, type?: string): Promise<HsnRow[]> {
  if (!clientId) return Promise.resolve([]);
  const key = `${clientId}::${type ?? ""}`;
  if (!hsnRecentCache.has(key)) {
    hsnRecentCache.set(
      key,
      (api.hsn.search("", { client_id: clientId, type, limit: 8 }) as Promise<ApiResp<HsnRow[]>>)
        .then((res) => res.data ?? [])
        .catch(() => {
          hsnRecentCache.delete(key);
          return [];
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
        .then((res) => res.data ?? [])
        .catch((e) => {
          hsnQueryCache.delete(key);
          throw e;
        }),
    );
  }
  return hsnQueryCache.get(key)!;
}
