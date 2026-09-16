/**
 * Accept an API payload only when it is the SHAPE the screen expects.
 *
 * WHY THIS EXISTS. `{ success, data, error }` says whether the call worked; it
 * says nothing about what `data` holds. A screen that does
 *
 *     if (!r.success) throw …
 *     setTrend(r.data)          // then later: trend.fys.length
 *
 * crashes on any response whose `data` is not the object it assumed — and
 * `[]` is truthy, so every `if (!trend)` guard on the screen passes it
 * straight through. Thirteen screens failed exactly this way the first time
 * the smoke walk was able to render them (16 Sep 2026); before that the walk
 * redirected to onboarding and none of it was visible.
 *
 * THIS IS NOT ONLY A TEST-HARNESS PROBLEM. Three production paths deliver a
 * body without the expected fields:
 *
 *   * the GST workspace router answers a refusal as HTTP 200 with
 *     `{success: false}` — CLAUDE.md records a screen that showed "Filed" for
 *     a request the server had declined;
 *   * `lib/api` aborts at 45 seconds and deliberately never retries;
 *   * Render's free tier cold-starts, so the first call after a sleep can
 *     return before the app is ready.
 *
 * THE RULE: a payload that is not the expected shape is NO DATA, not a crash.
 * Converting it to `null` (or `[]`) at the setter makes the screen's existing
 * empty and error states do their job, which is one line per screen instead of
 * a guard on every read — and it degrades the way a reader expects rather than
 * blanking the page.
 *
 * DELIBERATELY NOT A VALIDATOR. It does not check individual fields, because a
 * per-field schema in the browser would be a second description of the
 * backend's contract and this codebase already records what happens when one
 * of those drifts. It answers only "is this the right KIND of thing", which is
 * what separates a usable payload from `[]`, `null` and `"error"`.
 */

/** An object payload, or `null` when `data` is an array, a scalar or absent. */
export function objectOrNull<T>(data: unknown): T | null {
  if (data === null || typeof data !== "object") return null;
  if (Array.isArray(data)) return null;
  return data as T;
}

/** An array payload, or `[]` when `data` is anything else. */
export function arrayOrEmpty<T>(data: unknown): T[] {
  return Array.isArray(data) ? (data as T[]) : [];
}
