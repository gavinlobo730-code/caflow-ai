// The parties a client used most recently, at the top of its picker (POST-A-155).
//
// The order is the SERVER's (GET /api/customers/recent, /api/vendors/recent, read off the client's own newest
// documents); this only lays the ids over the list the editor already holds. An id the list does not hold (an
// inactive party, one the list has not loaded) is left out rather than invented, and nothing is pre-selected.
import { useEffect, useState } from "react";

export function recentFirst<T extends { id: string }>(ids: readonly string[], list: readonly T[]): T[] {
  const byId = new Map(list.map((p) => [p.id, p] as const));
  const out: T[] = [];
  for (const id of ids) {
    const p = byId.get(id);
    if (p) out.push(p);
  }
  return out;
}

/** The recent ids for a client, or none while loading, when off, or when the read failed (the list keeps its own order).
 *  `read` is a stable `api.customers.recent` / `api.vendors.recent`; a different one reads again. */
export function useRecentPartyIds(
  read: (clientId: string) => Promise<{ success: boolean; data?: { ids?: unknown } | null }>,
  clientId: string | null | undefined,
  enabled: boolean,
): string[] {
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    if (!enabled || !clientId) { setIds([]); return; }
    let cancelled = false;
    read(clientId)
      .then((res) => {
        if (cancelled) return;
        const got = res.success && Array.isArray(res.data?.ids) ? res.data.ids.filter((x): x is string => typeof x === "string") : [];
        setIds(got);
      })
      .catch(() => { if (!cancelled) setIds([]); });
    return () => { cancelled = true; };
  }, [read, clientId, enabled]);
  return ids;
}
