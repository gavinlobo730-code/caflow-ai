/**
 * How a rupee figure is rendered. One rule, and the arguments for each part.
 *
 * ── WHAT WAS THERE ──────────────────────────────────────────────────────────
 * 248 money formatters across `app/`, `components/` and `lib/`, in **26
 * distinct behaviours**, measured on 18 September 2026. The largest group —
 * 139 of them — has no `en-IN` locale at all, so it groups the WESTERN way
 * (₹1,234,567) or not at all, against decision D6, which says Indian grouping
 * everywhere: 12,34,567, never 1,234,567. About 150 are null-unsafe.
 *
 * `lib/services/formatting.formatPaise` is the nearest thing to an authority —
 * 73 files import it, and its grouping and its two decimals are right. Three
 * things about it are not, and each is why this module exists rather than a
 * patch to that one:
 *
 *   1. `formatPaise(undefined)` renders **"₹NaN"** on the screen.
 *   2. `formatPaise(null)` renders **"₹0.00"**, which is worse: a figure
 *      nobody holds is displayed as a figure somebody computed. This codebase
 *      makes that distinction load-bearing everywhere else — a nil on a return
 *      that means "we cannot see this" is not a nil that means "there was
 *      none" — and a money column is exactly where it gets read as an answer.
 *   3. It is `number`-only, and PostgREST returns a `bigint` as a STRING.
 *
 * ── THE RULES ───────────────────────────────────────────────────────────────
 * **INDIAN GROUPING, ALWAYS** (D6). `en-IN` with the currency style, which is
 * what produces ₹1,23,456.78 rather than ₹123,456.78.
 *
 * **TWO DECIMALS BY DEFAULT** (D5). Money crosses the API as integer paise and
 * a paisa is a real amount: an invoice for ₹1,18,000.50 that renders as
 * ₹1,18,000 does not tie to the ledger, and a column where some rows show
 * paise and some do not cannot be added up by eye.
 *
 * **A WHOLE-RUPEE FIGURE IS THE SERVER'S, NEVER THE BROWSER'S** — and that is
 * the part this module refuses rather than implements. D5's exception is the
 * return-prep screens, because GSTR-3B is filed in whole rupees. But the
 * rounding there is statutory: CGST §170, half rounded UP, and
 * `domain/gst/money.py` is the authority for it. A browser-side `round()` is a
 * SECOND implementation of a rounding rule, and it disagrees with the first at
 * exactly ₹x.50 — the value it is most often asked about. So `formatWhole`
 * takes a figure the server has ALREADY rounded, and a figure that is not a
 * whole number of rupees falls back to two decimals rather than rounding it:
 * a row visibly out of step with its neighbours is a bug somebody fixes, and a
 * silently different rounding on a return is a bug nobody sees until the
 * portal disagrees.
 *
 * **NOTHING AND ZERO ARE DIFFERENT.** `null` and `undefined` render as an
 * em dash, never ₹0.00. A caller that genuinely means zero passes 0.
 */

/** `null` and `undefined` render as this, not as a figure. */
export const NO_FIGURE = "—";

const GROUPED = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const GROUPED_WHOLE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/**
 * A paise figure as it arrives: an integer, or the STRING PostgREST returns
 * for a bigint, or absent. `"1,18,000"` is not one of those — a grouped string
 * is a rendering, not a value — so it reads as absent rather than as NaN.
 */
export type PaiseInput = number | string | null | undefined;

/** The integer paise, or null where there is no figure. */
export function toPaise(value: PaiseInput): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  // PostgREST hands back a bigint as a bare digit string. Anything else —
  // a grouped "1,18,000", an empty cell, a word — is not a figure, and
  // `Number()` would silently turn "" into 0, which is the defect above.
  const clean = value.trim();
  if (!/^-?\d+$/.test(clean)) return null;
  const n = Number(clean);
  return Number.isFinite(n) ? n : null;
}

/** ₹1,23,456.78 — the default everywhere. */
export function formatPaise(value: PaiseInput): string {
  const p = toPaise(value);
  return p === null ? NO_FIGURE : GROUPED.format(p / 100);
}

/**
 * ₹1,23,457 — for a figure the SERVER has already rounded to whole rupees.
 *
 * A figure carrying paise is NOT rounded here: it renders with its paise, so
 * the row stands out against its neighbours. Rounding it would be a second
 * implementation of CGST §170 living in a browser, and the two disagree at
 * exactly ₹x.50.
 */
export function formatWhole(value: PaiseInput): string {
  const p = toPaise(value);
  if (p === null) return NO_FIGURE;
  if (p % 100 !== 0) return GROUPED.format(p / 100);
  return GROUPED_WHOLE.format(p / 100);
}

/** True where `formatWhole` would fall back — a figure the server has not
 *  rounded reaching a screen that files in whole rupees. A return-prep screen
 *  can say so rather than leaving the reader to notice the odd row. */
export function carriesPaise(value: PaiseInput): boolean {
  const p = toPaise(value);
  return p !== null && p % 100 !== 0;
}

/**
 * The bare grouped number with no ₹ — for a column whose HEADER already says
 * the unit, which is most statutory tables. Same rules otherwise.
 */
const PLAIN = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatPaiseBare(value: PaiseInput): string {
  const p = toPaise(value);
  return p === null ? NO_FIGURE : PLAIN.format(p / 100);
}
