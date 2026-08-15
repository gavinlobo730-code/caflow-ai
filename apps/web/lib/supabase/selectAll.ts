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
 *
 * PAGES ARE FETCHED IN WIDENING WAVES, NOT ONE AT A TIME
 * ------------------------------------------------------
 * The obvious loop — request a page, wait, request the next — costs one full
 * round trip per 1000 rows. A client with 6000 invoices in a financial year
 * paid six round trips before its Sales tab could paint, and did so on every
 * visit. Nothing about page 3 depends on page 2, so nothing required that wait.
 *
 * The end of the data is still unknown until a short page comes back, so this
 * cannot simply fire everything at once. Instead the wave widens: 1 page, then
 * 2, then 4, then 4 … capped at `concurrency`.
 *
 *   ≤1000 rows  → 1 request,  1 wave   (unchanged — the overwhelming majority)
 *    2500 rows  → 3 requests, 2 waves  (was 3 waves)
 *   10000 rows  → 11 requests, 4 waves (was 11 waves)
 *
 * Starting at one is what keeps the common case honest: a client under the cap
 * must never pay for three speculative requests that return nothing.
 *
 * ON ERRORS, and the one behaviour this changed: the rows gathered BEFORE the
 * failing page are still returned with the error, and no further wave is
 * started — but the requests already in flight alongside the failing one do
 * finish. Their rows are discarded. There is no way to un-send a request, and
 * a caller that treats `error` as fatal (every caller does) cannot observe the
 * difference.
 */
export async function selectAll<T>(
  makeQuery: () => Rangeable<T>,
  pageSize = 1000,
  concurrency = 4,
): Promise<{ data: T[]; error: PostgrestError | null }> {
  const all: T[] = [];
  // Backstop against a misbehaving backend that never returns a short page —
  // far above any realistic SMB dataset (1000 pages × 1000 rows = 1M rows).
  const MAX_PAGES = 1000;
  const width = Math.max(1, Math.trunc(concurrency));

  let next = 0;
  while (next < MAX_PAGES) {
    // Double the wave each time until it reaches `concurrency`: 1, 2, 4, 4, …
    const wave = Math.min(width, next === 0 ? 1 : next + 1, MAX_PAGES - next);
    const pages = await Promise.all(
      Array.from({ length: wave }, (_unused, k) => {
        const from = (next + k) * pageSize;
        return makeQuery().range(from, from + pageSize - 1);
      }),
    );
    for (const { data, error } of pages) {
      if (error) return { data: all, error };
      const rows = data ?? [];
      all.push(...rows);
      // A short page is the end of the data. Anything fetched after it in this
      // same wave is past the end and is dropped.
      if (rows.length < pageSize) return { data: all, error: null };
    }
    next += wave;
  }
  return { data: all, error: null };
}

/** A thenable Supabase/PostgREST query that supports keyset paging. */
interface Keysettable<T> {
  gt: (column: string, value: unknown) => Keysettable<T>;
  order: (column: string, opts?: { ascending?: boolean }) => Keysettable<T>;
  limit: (
    n: number,
  ) => PromiseLike<{ data: T[] | null; error: PostgrestError | null }>;
}

/**
 * As `selectAll`, but paging by CURSOR instead of OFFSET.
 *
 * WHEN TO REACH FOR THIS INSTEAD
 * ------------------------------
 * Whenever the query EMBEDS a related table — `lines:journal_lines(...)`,
 * `items:invoice_lines(...)` and so on. With `.range()` (OFFSET), Postgres must
 * produce every row before the offset in order to skip it, and producing a row
 * means running its embedded aggregate. So the aggregate runs for the WHOLE
 * table on EVERY page.
 *
 * Measured on the Journal tab, one client, 12,836 entries with lines embedded:
 *
 *                       aggregate runs   time per page   buffers
 *     .range()  OFFSET      12,836         1,342 ms       54,180
 *     keyset                   835            32 ms       15,758
 *
 * Thirteen pages: about 17 seconds of database work against about 0.4. On a
 * shared instance, fired four-wide by selectAll's widening waves, the OFFSET
 * version did not merely run slowly — it failed, and the page showed
 * "Couldn't load journal entries".
 *
 * The backend hit exactly this and fixed it the same way; see
 * apps/api/domain/reporting/sources.py::_fetch_all and apps/api/core/db_paging.py.
 *
 * THE TRADE
 * ---------
 * Pages are SEQUENTIAL — each cursor comes from the previous page's last row,
 * so they cannot be fetched in parallel the way selectAll's waves are. On an
 * embedded query that loses nothing: thirteen sequential 32 ms seeks still beat
 * four concurrent 1.3 s materialisations by a wide margin. On a query with no
 * embed, `selectAll` remains the better choice.
 *
 * REQUIREMENTS
 * ------------
 * `key` must be unique and sortable, and must appear in the `.select(...)`
 * projection — the next cursor is read from the last row of each page. The
 * factory must NOT set its own `.order()` on the key; this adds it. Sort for
 * display after the walk finishes.
 */
export async function selectAllKeyset<T extends Record<string, unknown>>(
  makeQuery: () => Keysettable<T>,
  key = "id",
  pageSize = 1000,
): Promise<{ data: T[]; error: PostgrestError | null }> {
  const all: T[] = [];
  // Same backstop as selectAll: a cursor that never advances would otherwise
  // loop forever — a hang instead of a wrong answer is not an improvement.
  const MAX_PAGES = 1000;
  let cursor: unknown = undefined;

  for (let page = 0; page < MAX_PAGES; page++) {
    let q = makeQuery();
    if (cursor !== undefined) q = q.gt(key, cursor);
    const { data, error } = await q.order(key, { ascending: true }).limit(pageSize);
    if (error) return { data: all, error };

    const rows = data ?? [];
    all.push(...rows);
    // A short page is the end of the data — never an assumed row count.
    if (rows.length < pageSize) return { data: all, error: null };

    const last = rows[rows.length - 1]?.[key];
    if (last === undefined || last === null) return { data: all, error: null };
    cursor = last;
  }
  return { data: all, error: null };
}
