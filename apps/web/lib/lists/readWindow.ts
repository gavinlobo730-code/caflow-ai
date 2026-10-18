/**
 * Read a list the server answered as a WINDOW: `{ <rows>, has_more, limit, max_limit }` (apps/api/core/list_window.py).
 *
 * WHY ONE READER. Every screen that took a bare array from one of these endpoints took whatever came back as all of it,
 * and the window shape is one object with the same four fields on every endpoint that has one. Reading it once means a
 * screen cannot forget a field, cannot guess `has_more` from `rows.length === limit` (a scoped caller can be handed
 * fewer rows than the limit while more exist), and gets the rows as a real array whatever the payload was.
 *
 * It is not a validator of the rows (a per-row schema in the browser is a second description of the backend). It answers
 * the kinds: the rows are an array, `hasMore` is true only when the server said `true`, and the limits are numbers.
 *
 * A payload that is a bare array comes from a server that predates the window (the web app is deployed a few minutes ahead
 * of or behind the API). It is read as complete, which is what that server meant by it; there is no better answer to give
 * and the window closes when the API has rolled out.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

export interface ReadWindow<T> {
  rows: T[];
  /** True only when the server said `has_more: true`. */
  hasMore: boolean;
  /** The limit this window was read with. */
  limit: number;
  /** The server's ceiling for one read. */
  maxLimit: number;
}

/**
 * @param data the envelope's `data`
 * @param rowsField the key the rows sit under ("entities", "events")
 * @param askedLimit what the screen asked for, used when the server did not echo a limit
 * @returns the window, or `null` when `data` is neither a window nor a bare array (a refusal, `null`, a scalar): the
 *          screen then says the list could not be read, which is a different statement from an empty one
 */
export function readWindow<T>(data: unknown, rowsField: string, askedLimit: number): ReadWindow<T> | null {
  if (Array.isArray(data)) {
    return { rows: data as T[], hasMore: false, limit: askedLimit, maxLimit: askedLimit };
  }
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj) return null;
  if (!(rowsField in obj)) return null;
  const limit = typeof obj.limit === "number" && Number.isFinite(obj.limit) ? obj.limit : askedLimit;
  const maxLimit = typeof obj.max_limit === "number" && Number.isFinite(obj.max_limit) ? obj.max_limit : limit;
  return {
    rows: arrayOrEmpty<T>(obj[rowsField]),
    hasMore: obj.has_more === true,
    limit,
    maxLimit,
  };
}
