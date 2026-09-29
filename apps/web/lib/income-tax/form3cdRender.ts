/**
 * Rendering a Form 3CD derived clause's value — a number, a string, a list,
 * or a nested object — as prose a CA reads, never as raw JSON.
 *
 * Clause 26 (§43B sums) returns `{msme_sums_disallowed_paise, gaps: [...]}`
 * from `domain/income_tax/section_43b_h.py` by way of
 * `services/form_3cd_service.py`, and the page's own `renderValue` used to
 * fall straight to `JSON.stringify(value, null, 2)` for anything that was
 * not a plain string or number — which every OBJECT-shaped clause is. So a
 * gap list, already fixed upstream to be one line per vendor rather than one
 * per bill (see section_43b_h.py's own history: 29 unclassified vendors with
 * 25-36 bills each rendered as ~755 duplicated lines before that fix), still
 * came out as a single `<pre>` block of literally-quoted, comma-joined JSON
 * text — because the OBJECT wrapping it had no formatting of its own.
 *
 * Extracted out of the page (which has JSX and so cannot be `node --test`ed
 * directly, per this repo's frontend test convention of reading and
 * exercising plain source) so this formatting logic — and the duplication it
 * would silently re-hide if the JSON fallback ever came back — is pinned by
 * an ordinary unit test rather than only by eyeballing a screenshot.
 */

/** snake_case -> "Snake case", for an OBJECT KEY nobody wrote a label for.
 *  Never applied to a clause's own strings (a gap sentence, a reason) —
 *  those are prose already and re-casing them would mangle capitalised
 *  section citations like "§43B(h)". */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * A best-effort, honest rendering of whatever a derived clause returned,
 * without pretending to know the shape of every one of them:
 *
 *   - a list renders as one bulleted line per item, never a JSON array
 *     literal — so N distinct gap sentences read as N lines, not as one
 *     giant quoted-and-comma-joined blob;
 *   - an object renders as one "Label: value" line per field, each value
 *     formatted by this SAME function — so a list nested inside an object
 *     (clause 26's `gaps`) still gets the bulleted treatment rather than
 *     falling through the object branch straight to JSON;
 *   - `JSON.stringify` is the LAST resort, for a value shaped unlike either
 *     of the two shapes every clause actually returns (a list, or a flat-ish
 *     object) — not the first thing tried.
 */
export function renderClauseValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return value.map((item) => `• ${renderClauseValue(item)}`).join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "—";
    return entries
      .map(([k, v]) => `${humanizeKey(k)}: ${renderClauseValue(v)}`)
      .join("\n");
  }
  return JSON.stringify(value);
}
