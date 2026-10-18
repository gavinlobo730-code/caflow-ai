/**
 * A list that stops at a number says it stopped.
 *
 * The server asks the database for one row more than the window and answers
 * `has_more` (apps/api/core/list_window.py), so a screen never has to guess
 * whether the rows it was handed are all of them. This module is the browser's
 * half and holds NO number of its own: the ceiling comes from the server
 * (`max_limit`), because a copy here is a second place for the two to disagree.
 *
 * Only wording and the step live here. Whether more exist is the server's
 * answer, never a comparison of `rows.length` to the limit that was asked for
 * (a scoped caller can be handed fewer rows than the limit while more exist).
 */

/** How many more rows one "show more" asks for. */
export const WINDOW_STEP = 100;

/**
 * The ceiling for a window the browser reads DIRECTLY from the database (a
 * task list), where no server answer carries `max_limit`. It equals the API's
 * `MAX_LIST_LIMIT` on purpose; a window read through the API takes the
 * server's figure instead.
 */
export const DIRECT_READ_WINDOW_MAX = 500;

/**
 * The most entities one read of the firm's entity register may ask for. The register screen loads the list whole and
 * searches, sorts and filters it in the browser, so it asks for the ceiling. It is the one browser-side copy of
 * `ENTITY_LIST_MAX` in apps/api/routers/relationships.py and a test holds the two equal.
 */
export const ENTITY_REGISTER_WINDOW_MAX = 2000;

/**
 * The most pipeline leads one read may ask for. The pipeline board loads its leads whole and groups them by stage, so it
 * asks for the ceiling. It is the one browser-side copy of `LEAD_LIST_MAX` in apps/api/routers/lifecycle.py and a test
 * holds the two equal.
 */
export const LEAD_REGISTER_WINDOW_MAX = 2000;

/** The limit to ask for next, or null when the ceiling has been reached. */
export function nextWindowLimit(limit: number, maxLimit: number): number | null {
  if (!Number.isFinite(limit) || !Number.isFinite(maxLimit)) return null;
  if (limit >= maxLimit) return null;
  return Math.min(limit + WINDOW_STEP, maxLimit);
}

/** What the window holds, in words: "the latest 100 time entries". */
export function windowDescription(
  shown: number,
  noun: string,
  order: "latest" | "first",
  qualifier?: string,
): string {
  const base = `the ${order} ${shown} ${noun}`;
  return qualifier ? `${base}, ${qualifier}` : base;
}

/** The one sentence a cut-short list carries. */
export function windowSentence(what: string): string {
  return `Showing ${what}. More exist that are not shown here.`;
}
