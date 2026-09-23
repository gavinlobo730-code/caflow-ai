// The palette, as VALUES, for the places a Tailwind class cannot reach.
//
// ─────────────────────────────────────────────────────────────────────────────
// WHY THIS EXISTS
// ─────────────────────────────────────────────────────────────────────────────
// `tailwind.config.ts` is the authority for colour and it is a *Tailwind*
// config, so what it declares reaches a class and nothing else. An inline
// `style={{ backgroundColor: … }}`, an SVG `stroke=`, a prop default and a
// chart series colour are none of them classes, so three screens threaded raw
// hex through all four — and the token ratchet left them uncounted with its
// reason stated plainly: they "are not classes and have no token to use".
//
// That reason was true, and it was the whole defect. This module is the token
// to use.
//
// It is `apps/api/services/pdf_style.py`'s shape, deliberately: that module was
// written when six PDFs had picked four different header fills, and it works
// because every value carries the name of the token it came from, so a guard
// can pin the two together rather than trusting a copy. Same palette, same
// method, the browser's side of it.
//
// ─────────────────────────────────────────────────────────────────────────────
// PREFER A CLASS. THIS IS THE FALLBACK, NOT THE FRONT DOOR.
// ─────────────────────────────────────────────────────────────────────────────
// `className="bg-brand"` is better than `style={{ backgroundColor: BRAND }}`
// in every way a stylesheet is better than an inline attribute — it cascades,
// it can be overridden, it costs no specificity fight, and Tailwind can purge
// it. Reach for this module only where there is no class to reach for:
//
//   • an SVG presentation attribute (`stroke`, `fill`) on an element whose
//     colour is computed
//   • a value passed as a PROP and used as a style, where the component cannot
//     know the class ahead of time
//   • a chart or canvas series colour
//
// A `style={{}}` written because it was quicker than finding the class is not
// one of those, and the guard cannot tell them apart — only the author can.

/* ── Brand ──────────────────────────────────────────────────────────────────
   ONE primary. The config's own comment records why this needed saying:
   "there was no single primary, so three were in use at once — brand navy
   here, indigo #4338CA in banking, blue-700 on the Team screen". The navy is
   the brand; the other two were rivals, and they lose. */
export const BRAND = "#182350";
export const BRAND_DARK = "#0D1635";
export const BRAND_LIGHT = "#AFD2FA";

/** A tinted fill behind a brand-ish or active mark — an icon chip, an empty
 *  state's medallion. NOT `ps.hover`, which means a row under the cursor: a
 *  static fill borrowing a hover token is the `state.ready-hover` trap the PDF
 *  pass recorded, where the nearest hex happened to mean something else. */
export const BRAND_SURFACE = "#EFF6FF";

export const GOLD = "#B9915E";
export const GOLD_SURFACE = "#FEFAEF";

/* ── Ink, by role ───────────────────────────────────────────────────────────
   Four steps so an interactive muted text can darken exactly one and still
   move. `hint` is the one that was #94A3B8 — 2.56:1 on white — until the token
   pass moved it; anything still writing that literal is reproducing the bug. */
export const INK = "#0D1635";
export const BODY = "#334155";
export const LABEL = "#475569";
export const HINT = "#64748B";
export const DISABLED = "#CBD5E1";

/* ── Surfaces ───────────────────────────────────────────────────────────────*/
export const BG = "#F8FAFC";
export const SURFACE = "#FFFFFF";
export const MUTED = "#F1F5F9";
export const HOVER = "#E9EFF6";
export const BORDER = "#E2E8F0";
export const BORDER_STRONG = "#CBD5E1";

/* ── State ──────────────────────────────────────────────────────────────────
   Three values, and three is the whole vocabulary: is this ready, does it need
   me, did it go wrong. A screen with a four-band ramp collapses the middle two
   UPWARD into `attention` rather than reaching for a fourth shade — the config
   refuses a numbered scale for the same reason, that it "is just slate with
   different names and gives the next author no guidance".

   These are darker than the green-600 / amber-600 / red-600 the screens used
   to write, which is the point: they are the contrast-audited values, and a
   swap can only raise the ratio. */
export const READY = "#047857";
export const READY_SURFACE = "#ECFDF5";
export const READY_SOLID = "#059669";
export const ATTENTION = "#B45309";
export const ATTENTION_SURFACE = "#FFFBEB";
export const PROBLEM = "#B91C1C";
export const PROBLEM_SURFACE = "#FEF2F2";
export const DONE = "#475569";

/* ── Money direction, which is NOT state ────────────────────────────────────
   A withdrawal is not a problem — it is half of what a bank account does. */
export const MONEY_IN = "#15803D";
export const MONEY_OUT = "#9F1239";
export const MONEY_NEGATIVE = "#7F1D1D";

/**
 * Where each value above comes from in `tailwind.config.ts`.
 *
 * This is what makes the module checkable rather than a second palette: the
 * guard resolves each path in the config and asserts the value here equals it.
 * A token that moves there and not here fails; a value invented here that the
 * config does not hold fails too. Both directions matter — the Schedule III
 * caption list drifted for months because only one of them was asserted.
 */
export const TOKEN_SOURCE: Record<string, string> = {
  BRAND: "brand.DEFAULT",
  BRAND_DARK: "brand.dark",
  BRAND_LIGHT: "brand.light",
  BRAND_SURFACE: "brand.surface",
  GOLD: "gold.DEFAULT",
  GOLD_SURFACE: "gold.surface",
  INK: "ps.ink",
  BODY: "ps.body",
  LABEL: "ps.label",
  HINT: "ps.hint",
  DISABLED: "ps.disabled",
  BG: "ps.bg",
  SURFACE: "ps.surface",
  MUTED: "ps.muted",
  HOVER: "ps.hover",
  BORDER: "ps.border",
  BORDER_STRONG: "ps.border-strong",
  READY: "state.ready",
  READY_SURFACE: "state.ready-surface",
  READY_SOLID: "state.ready-solid",
  ATTENTION: "state.attention",
  ATTENTION_SURFACE: "state.attention-surface",
  PROBLEM: "state.problem",
  PROBLEM_SURFACE: "state.problem-surface",
  DONE: "state.done",
  MONEY_IN: "money.in",
  MONEY_OUT: "money.out",
  MONEY_NEGATIVE: "money.negative",
};

/** Every exported value, keyed by its export name, for the guard to walk. */
export const TOKEN_VALUES: Record<string, string> = {
  BRAND, BRAND_DARK, BRAND_LIGHT, BRAND_SURFACE,
  GOLD, GOLD_SURFACE,
  INK, BODY, LABEL, HINT, DISABLED,
  BG, SURFACE, MUTED, HOVER, BORDER, BORDER_STRONG,
  READY, READY_SURFACE, READY_SOLID,
  ATTENTION, ATTENTION_SURFACE, PROBLEM, PROBLEM_SURFACE, DONE,
  MONEY_IN, MONEY_OUT, MONEY_NEGATIVE,
};
