import type { PostgrestError } from "@supabase/supabase-js";

/** A thenable Supabase/PostgREST query that supports `.range()`. */
interface Rangeable<T> {
  range: (
    from: number,
    to: number,
  ) => PromiseLike<{ data: T[] | null; error: PostgrestError | null }>;
}

/**
 * Fetch *every* row for a Supabase query, paging past PostgREST's default
 * row ceiling so large lists are never silently truncated.
 *
 * PostgREST caps a single response (commonly 1000 rows). A client with more
 * invoices / bills / journal-entries than the cap would otherwise receive only
 * the first page — and every in-memory total, filter and search computed from
 * that page would be silently wrong. This loops `.range()` until a short page
 * signals the end, mirroring the backend's own paged fetch
 * (apps/api/domain/reporting/sources.py::_fetch_all).
 *
 * Pass a factory, not an already-built query: PostgREST builders are single-use
 * (awaiting one executes it), so we rebuild for each page.
 *
 *   const { data, error } = await selectAll(() =>
 *     supabase.from("client_sales_invoices").select("*")
 *       .eq("client_id", id)
 *       .order("invoice_date", { ascending: false })
 *       .order("id"));            // stable, total ordering
 *
 * Always give the query a stable, *total* ordering — add a unique tiebreaker
 * (e.g. `id`) when the primary sort key is not unique — otherwise rows can
 * shift between pages and be duplicated or skipped.
 */
export async function selectAll<T>(
  makeQuery: () => Rangeable<T>,
  pageSize = 1000,
): Promise<{ data: T[]; error: PostgrestError | null }> {
  const all: T[] = [];
  let from = 0;
  // Backstop against a misbehaving backend that never returns a short page —
  // far above any realistic SMB dataset (1000 pages × 1000 rows = 1M rows).
  const MAX_PAGES = 1000;
  for (let page = 0; page < MAX_PAGES; page++) {
    const { data, error } = await makeQuery().range(from, from + pageSize - 1);
    if (error) return { data: all, error };
    const rows = data ?? [];
    all.push(...rows);
    if (rows.length < pageSize) return { data: all, error: null };
    from += pageSize;
  }
  return { data: all, error: null };
}
