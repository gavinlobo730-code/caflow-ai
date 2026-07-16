/**
 * Run `fn` over `items` with at most `limit` in flight at once, preserving
 * result order. Bulk row actions (Receive, Delete, Send, ...) each fan out
 * to one backend request per selected row; firing all of them via a single
 * `Promise.all` works fine for a handful of rows but falls over once a
 * selection reaches into the hundreds — the browser can't sustain that many
 * simultaneous connections and a chunk of them abort with "Failed to fetch"
 * (observed with 250 Purchase Bills selected at once). Capping concurrency
 * keeps every bulk action correct regardless of selection size.
 */
export async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i], i);
    }
  }
  const workers = Array.from({ length: Math.min(limit, items.length) }, () => worker());
  await Promise.all(workers);
  return results;
}
