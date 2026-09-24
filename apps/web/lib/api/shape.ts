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

/**
 * An object payload whose named fields are guaranteed to be arrays.
 *
 * WHY THIS EXISTS. `objectOrNull` is necessary and NOT sufficient, which is
 * the thing that keeps being got wrong: it answers whether `data` is the right
 * KIND of thing, so it converts `[]`, `null` and a scalar to `null` — and `{}`
 * passes straight through. A screen that then does `report.groups.map(...)`
 * still throws, and its `if (!report)` guard does not see it coming because
 * `{}` is truthy. Both components CLAUDE.md records as having crashed the
 * 24-09-2026 smoke walk failed exactly there.
 *
 * So the two halves belong together, and doing them ONCE at the setter beats
 * doing them at every read: a read added next year is covered without anybody
 * remembering, and the fields that are lists are named in one visible place
 * instead of implied by a `.map` somewhere in the JSX.
 *
 * DELIBERATELY NOT A VALIDATOR, for the reason the module header gives. It
 * does not check that a field is PRESENT, or that its elements are the right
 * shape — a per-field schema in the browser would be a second description of
 * the backend's contract. It answers one question: could a `.map` on this
 * field throw.
 *
 *     setData(objectWithLists<StockAgeing>(r.data, "bands", "items", "notes"))
 */
export function objectWithLists<T extends object>(
  data: unknown,
  ...listFields: (keyof T & string)[]
): T | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj) return null;
  const out: Record<string, unknown> = { ...obj };
  for (const f of listFields) out[f] = arrayOrEmpty(out[f]);
  return out as T;
}
