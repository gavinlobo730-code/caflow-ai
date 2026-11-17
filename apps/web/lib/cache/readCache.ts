/**
 * The one read cache: a keyed store of answers to idempotent reads, with single-flight, and stale-while-revalidate for the lists a person returns to
 * (POST-A-124).
 *
 * WHY. Every tab switch, client switch and back-navigation re-fetched a list and drew a skeleton over Singapore-to-Mumbai latency, though the list
 * the person looked at a minute ago is almost always the list they are about to see. `lib/accounting/reportCache.ts` was the only cache and held reports;
 * it is now a thin user of THIS module, so there is one store, one single-flight and one way to clear (not a third cache beside it).
 *
 * THE RULES, each held by `scripts/the-read-cache-is-opt-in-and-never-feeds-a-write.test.ts`:
 *   1. OPT-IN PER READ. Nothing here wraps `request()` or the Supabase client; a read is cached only where its screen calls `readStale` or `cachedReport`,
 *      and the callers are a listed set with a reason.
 *   2. IDEMPOTENT READS ONLY, AND NEVER A FIGURE THAT MUST BE CURRENT AT THE MOMENT OF A WRITE. A stale answer is a first paint, always followed by a real
 *      read; it is never what a form validates against, a posting, a balance check or a statutory figure is built from.
 *   3. A SCREEN SAYS WHEN THE ANSWER IT PAINTED WAS READ (`readAt`), and says it is refreshing until the real answer lands.
 *   4. A PERSON'S OWN WRITE CLEARS WHAT IT CHANGED (`forgetReads(prefix)`), and a SIGN-OUT OR A DIFFERENT PERSON CLEARS EVERYTHING (`bindReadCacheToUser`): one
 *      browser tab can be handed to another member, and their list must not be painted from the last one's.
 *   5. THE STORE IS IN MEMORY. Nothing is written to localStorage, so a reload starts empty and nothing outlives the tab.
 *
 * Keys are `|`-joined parts, the first of which is the family (`clients`, a client id for the reports); `forgetReads("clients")` clears every key of a family.
 */
import { formatTime } from "../dates/format.ts";

type Entry = { ts: number; data: unknown };

const store = new Map<string, Entry>();
/** Requests in flight, by key: a second caller for the same key awaits the first one's request instead of starting its own (apex-accounting-reports-12). */
const inFlight = new Map<string, Promise<unknown>>();
/** Bumped by every clear, so an answer that was in flight when its key was cleared is not stored over the clear (a write landed while the read was out). */
let epoch = 0;
let boundUser: string | null | undefined;

export function readKey(parts: (string | undefined)[]): string {
  return parts.map((p) => p ?? "").join("|");
}

export function peekRead(key: string): { data: unknown; readAt: number } | undefined {
  const e = store.get(key);
  return e ? { data: e.data, readAt: e.ts } : undefined;
}

export function storeRead(key: string, data: unknown): void {
  store.set(key, { ts: Date.now(), data });
}

/** Run `fetcher` once per key at a time; store its answer unless the key was cleared while it was out. */
export function singleFlight<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key);
  if (existing) return existing as Promise<T>;
  const bornIn = epoch;
  const promise = (async () => {
    try {
      const data = await fetcher();
      if (bornIn === epoch) storeRead(key, data);
      return data;
    } finally {
      inFlight.delete(key);
    }
  })();
  inFlight.set(key, promise);
  return promise;
}

/**
 * Stale-while-revalidate for a list a person returns to. `onStale` is called AT ONCE with the last answer (and when it was read) if there is one; the real
 * read ALWAYS runs, and its answer is what the promise returns. A failure of the real read rejects, so the screen reports it as it did before; a painted
 * stale answer is then left on screen and the screen must say the refresh failed.
 */
export async function readStale<T>(
  key: string,
  fetcher: () => Promise<T>,
  onStale?: (data: T, readAt: number) => void,
): Promise<T> {
  const hit = store.get(key);
  if (hit && onStale) onStale(hit.data as T, hit.ts);
  return singleFlight(key, fetcher);
}

/** Forget one key, or every key of a family (`forgetReads("clients")` clears `clients|active`, `clients|all`, …). Called by a person's own write. */
export function forgetReads(family?: string): void {
  epoch += 1;
  if (!family) { store.clear(); inFlight.clear(); return; }
  for (const k of Array.from(store.keys())) if (k === family || k.startsWith(family + "|")) store.delete(k);
  for (const k of Array.from(inFlight.keys())) if (k === family || k.startsWith(family + "|")) inFlight.delete(k);
}

/** Tell the cache who is signed in. A different person, or nobody, empties it. */
export function bindReadCacheToUser(userId: string | null): void {
  if (boundUser !== undefined && boundUser !== userId) forgetReads();
  boundUser = userId;
}

/** How a screen words when a painted answer was read: `3:30 pm`, in IST, by the one date module. */
export function readAtText(readAt: number): string {
  return formatTime(new Date(readAt).toISOString());
}
