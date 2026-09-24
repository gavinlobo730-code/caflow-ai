// Colour and type size come from the token file, and neither budget may grow.
// Run with:
//   node --experimental-strip-types --test scripts/a-colour-and-a-type-size-come-from-the-token-file.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `tailwind.config.ts` has carried `brand`, `gold` and the `ps.*` scales since
// the product was built, and on 18 September 2026 the app still held **10,231
// raw hex literals across 65 values** against roughly a thousand token uses —
// about 9% of colour decisions going through the token layer. Type was worse:
// **2,252 arbitrary `text-[Npx]`**, 1,860 of them at 10px or 11px, which are
// BELOW Tailwind's smallest named size, so there was nothing to converge on
// even in principle.
//
// That is not a tidiness problem. The most-used colour in the product was
// `#94A3B8` — 1,567 sites, most of them at 10px or 11px — rendering at
// **2.56:1 on white**, well under WCAG 1.4.3's 4.5:1. A literal cannot be
// fixed centrally: the token moved and 1,567 places did not.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, AND WHY IT IS A RATCHET RATHER THAN A BAN
// ─────────────────────────────────────────────────────────────────────────────
// A ban would fail on the first commit and stay failing, so nobody could land
// anything until the whole migration was done. A ratchet fails only on a
// change that makes it WORSE, which is the property that actually holds the
// line — the same shape as the reachability ratchet and the unreadable-
// references budget.
//
// Two budgets, both counted over `app/`, `components/` and `lib/`:
//
//   1. raw hex inside a Tailwind arbitrary value — `text-[#0F172A]` and friends
//   2. arbitrary font sizes — `text-[13px]`
//
// A bare "#0F172A" STRING is not counted: a chart series colour, a jsPDF
// setTextColor, an SVG attribute are not classes and have no token to use.
// What is counted is the bracket syntax, which is always a class.
//
// ─────────────────────────────────────────────────────────────────────────────
// AND A CLASS NAME IS NEVER BUILT
// ─────────────────────────────────────────────────────────────────────────────
// Tailwind scans SOURCE TEXT. `text-${color}-600` produces a class at runtime
// that was never emitted at build time, so the element silently gets no colour
// at all. `components/banking/BankBook.tsx` has recorded that rule in a comment
// since it was written; `app/clients/[id]/payroll/page.tsx` broke it, and all
// four statutory-challan figures rendered in the inherited body colour with the
// colour coding a CA reads at a glance absent. The comment was not enough, so
// the rule is asserted here.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOTS = ["app", "components", "lib"];

/** Every .ts/.tsx under the roots. */
function sources(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      sources(path, out);
    } else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

const FILES = ROOTS.flatMap((r) => sources(r));
const BODIES = FILES.map((f) => ({ file: f, body: readFileSync(f, "utf8") }));

/** A hex colour used as a Tailwind arbitrary value: `border-[#E2E8F0]`. */
const HEX_CLASS = /[a-zA-Z][a-zA-Z-]*-\[#[0-9a-fA-F]{3,8}\]/g;
/** An arbitrary font size: `text-[13px]`. */
const PX_TEXT = /\btext-\[\d+(\.\d+)?px\]/g;

/** Comments stripped first — the SAME treatment the interpolation test below
 *  already gives its own scan, and for the reason recorded there: "a guard that
 *  fails on the documentation of its own rule is a guard nobody keeps."
 *
 *  This function did NOT strip, so a comment explaining WHY a token was used
 *  instead of `text-[9px]` counted as a `text-[9px]`. Found on 24-09-2026 by a
 *  chip that used the token correctly and still pushed the total one over
 *  budget — the fix for which would have been to raise the budget, hiding a
 *  real arbitrary value behind a prose one. The lesson was already written
 *  forty lines below and had not been applied to its neighbour. */
function count(re: RegExp): { total: number; byFile: Map<string, number> } {
  const byFile = new Map<string, number>();
  let total = 0;
  for (const { file, body } of BODIES) {
    const code = body
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
    const n = (code.match(re) ?? []).length;
    if (n) { byFile.set(file, n); total += n; }
  }
  return { total, byFile };
}

// ── The budgets ─────────────────────────────────────────────────────────────
//
// LOWER THESE as the migration proceeds; never raise one. A number that goes
// up is the thing this file exists to refuse.
//
// 18 Sep 2026, before this pass:  hex 10,146   ·  arbitrary text size 2,265
// 18 Sep 2026, after it:          hex     116   ·  arbitrary text size 2,265
//
// 18 Sep 2026, after the T4 rename:   arbitrary text size 405
//
// The rename moved 1,855 sites — 994 at 10px and 861 at 11px — onto `text-3xs`
// and `text-2xs`. It is a PURE rename: both steps are bare font sizes, so
// `.text-\\[10px\\]{font-size:10px}` and `.text-3xs{font-size:10px}` are the
// same declaration, verified in the built stylesheet before and after.
//
// THE 405 LEFT ARE NOT RENAMES AND THAT IS WHY THEY ARE LEFT. `text-[12px]`
// (202) and `text-[14px]` (40) are exactly Tailwind's own `text-xs` and
// `text-sm` — but those set a LINE-HEIGHT as well (12px/16px, 14px/20px), so
// the substitution would change leading on 242 sites. `text-[13px]` (88) has
// no name at all, and `text-[9px]` (29) deliberately has none: it is below the
// size at which the remaining steps are distinguishable, and naming it would
// bless it. Each needs a decision, which belongs with the reference screens.
//
// 380 → 277 on 24-09-2026, AND THE REFERENCE SCREENS ARE WHAT DECIDED IT.
// 103 of the 380 — 27% — were in SIX files: login, signup, forgot-password,
// reset-password, portal/login and portal/activate, carrying 32/26/22/18/16/
// 14/13/12px. That is not sprawl, it is a family with its own ladder, written
// as arbitrary values because three of its steps (22, 26, 32) sit BETWEEN
// Tailwind's. They now take `text-xs`/`sm`/`base`/`lg`/`xl`/`2xl`/`3xl`, which
// moves those three by 2px each and pulls the leading in on every one — so
// this was decided by looking, not by arithmetic: the smoke walk was run
// before and after and the four observable screens read as neutral-to-better,
// slightly more compact, nothing broken. 13px and 14px both went to `text-sm`
// deliberately: they were never two steps, and collapsing them widens the gap
// to the 12px caption beside them from 1px to 2px.
//
// The other two screens could not be photographed at all, which is the half
// worth keeping: the walk SIGNS IN, so `/login` and `/login/forgot-password`
// bounced to `/`. `--anon` was added for exactly this and the pair was read
// before and after like the rest.
// 98 → 44 on 24-09-2026. The 54 removed were ONE colour family in five files:
// the indigo the config's own comment names as a rival primary — "#4338CA in
// banking" — carried by `components/ui/data-table.tsx` (18, every one of them
// the SELECTION affordance, so every screen using DataTable inherited it) and
// by the bulk-action bars three screens render beside it. The portal's tax tab
// held the OTHER two rivals, blue-700 as a primary and its own emerald for
// "ready". Mapped by ROLE — the accent to `brand`, its hover step to
// `brand-dark`, a white chip under the cursor to `ps-hover`, which is what
// that token means — never by nearest value.
const HEX_BUDGET = 44;
// 392 → 289 on 24-09-2026, the auth family converted (see above). Lowered to
// what is actually there each time, because a budget with slack in it is a
// budget that permits a regression.
//
// ⚠️ THE 289 WAS NOT 277, AND THE 12 WERE A FINDING. `PX_TEXT` matches a
// DECIMAL (`\d+(\.\d+)?px`) and the census everyone had been quoting —
// including THE-PLAN's own DONE WHEN — greps `text-\[[0-9]+px\]`, which does
// not. So thirteen `text-[12.5px]` were invisible to every count taken so far,
// and twelve were in ONE family: `ActivityRail` and the seven panels of
// `ContextPanel`, the navigation chrome on every screen in the product. A HALF
// PIXEL is not a step of any scale — it is what you write when you are nudging
// one label against another. THE-PLAN's metric was corrected to this regex:
// a metric and the guard that enforces it must count the same population,
// which this file's own history already records going wrong once.
//
// 289 → 277, that family converted to `text-xs`. It shows on 90 of the 160
// routes, which is what a shell change means, and the walk was run before and
// after on all of them: the rail and the context panel come out a shade
// tighter (Tailwind's 16px leading in place of the ~19px these inherited) and
// nothing else moves.
//
// 277 → 187, PAYROLL — 90 sites in five files, the largest module left. Same
// mapping as the auth family (12→xs, 13 and 14→sm), plus two one-offs decided
// per site rather than by rounding: the page's `text-[15px]` h1 goes UP to
// `text-base`, because `text-sm` would make the heading the same size as the
// body under it; and the one `text-[9px]` chip takes `text-3xs`, the smallest
// step there is, on T3-a's recorded decision that 9px gets no name of its own.
//
// ⚠️ ONLY ONE OF THE 160 ROUTES MOVED, AND THAT IS A LIMIT OF THE WALK RATHER
// THAN OF THE CHANGE. 71 of the 90 sites are inside `EmployeeDrawer`,
// `StatutoryHandoff` and `ApplyStructureModal`, which open on a click and on
// data; the walk renders with neither. What the walk DID confirm is the
// negative: 159 routes byte-identical, so nothing leaked out of the module.
//
// **187 → 0 on 24-09-2026. D12 IS DONE AND THE BUDGET IS NOW A BAN.** The tail
// was 54 files with nothing left to group: 113 × 12px, 35 × 13px, 29 × 9px,
// 4 × 18px, 3 × 14px, 2 × 15px and the dashboard's one 22px greeting. The 29
// nine-pixel sites — chips, badges and micro-labels — take `text-3xs` (10px)
// rather than a token of their own, because naming 9px is the one thing T3-a
// decided against and it gave the reason: below that the remaining steps stop
// being distinguishable. The two 15px modal titles go UP to `text-base` for
// the payroll h1's reason.
//
// 149 of the 160 routes moved, which is what "the tail" means, and the eleven
// that did not are the ones with no arbitrary size left to convert. The
// biggest movers were read: the dashboard (greeting 22→20, card headings and
// deadline names 13→14, so the names read more clearly against their dates)
// and `/practice/compliance` (labels a shade larger, everything shifted a few
// pixels up, layout unchanged). Nothing needed a hand-set `leading-*`.
//
// A ZERO BUDGET IS A DIFFERENT THING FROM A SMALL ONE: there is no longer a
// number to raise. If a size is genuinely needed that the scale does not
// carry, the answer is a token in `tailwind.config.ts` with the reason beside
// it — which is how `3xs` and `2xs` came to exist — not an arbitrary value
// and a bigger budget here.
const PX_TEXT_BUDGET = 0;

// ── THE SECOND WAY TO WRITE A COLOUR, WHICH THIS FILE COULD NOT SEE ─────────
//
// `HEX_CLASS` matches a Tailwind ARBITRARY VALUE — `border-[#E2E8F0]`. A hex in
// a `style={{ backgroundColor: "#182350" }}`, an SVG `stroke=`, a prop default
// or a chart palette is the same defect and matched nothing, so a file could
// hold thirty raw colours and pass a guard whose own name is "a colour comes
// from the token file". Measured on 19 Sep 2026: 46 of them once comments and the
// allowlist below are taken out, in 3 files.
//
// FOUR OF THOSE FILES ARE LEGITIMATE and are allowlisted with their reason
// rather than counted, because a budget that includes sites nobody should ever
// convert never reaches nil and stops meaning anything:
//
//   app/global-error.tsx    the ROOT error boundary. It renders when the app
//                           itself failed, which may be before the stylesheet
//                           loaded, so a Tailwind class cannot be relied on.
//   app/layout.tsx          <meta name="theme-color"> takes no class.
//   components/LogoIcon.tsx the brand mark's own SVG.
//   app/settings/branding/  a colour PICKER — hex is its data, not its style.
//   app/sign/page.tsx       a print stylesheet injected as a string.
//
// The rest — the executive dashboard, copilot and workflows — thread colours
// through `style={{}}` and prop defaults, and every one of them maps to a token
// or a Tailwind palette class. Converting them is per-component work on three
// screens and it is what lowers this budget.
//
// ── 24 SEPTEMBER 2026: 46 → 0, AND WHAT MADE IT POSSIBLE ────────────────────
// The sentence above — "have no token to use" — was true and was the whole
// defect. `tailwind.config.ts` is a Tailwind config, so what it declares
// reaches a class and nothing else; a `style={{}}`, an SVG `stroke=` and a prop
// default had nothing to reach for, which is why three screens still held 46
// literals and one of them coloured an inactive icon **#94A3B8**, the very
// value this file records `ps.hint` moving OFF at 2.56:1.
//
// `lib/design/tokens.ts` is the token to use, pinned to the config in both
// directions by `one-palette-and-the-browser-reads-it.test.ts`. The three
// screens now import it and the counted population is nil.
const RAW_HEX = /#[0-9a-fA-F]{6}\b/g;
const HEX_OUTSIDE_A_CLASS_BUDGET = 0;
const HEX_LITERAL_IS_THE_POINT = [
  "app/global-error.tsx",
  "app/layout.tsx",
  "components/LogoIcon.tsx",
  "app/settings/branding/page.tsx",
  "app/sign/page.tsx",
  // The palette module itself. Hex is its DATA, the same exemption the colour
  // picker has — it is the one file whose job is to hold these values, and the
  // guard that checks it is a different one: every value here must equal what
  // `tailwind.config.ts` declares at its named path, asserted both ways.
  "lib/design/tokens.ts",
];

test("a colour is not written as a raw hex anywhere else either", () => {
  const byFile = new Map<string, number>();
  let total = 0;
  for (const { file, body } of BODIES) {
    if (HEX_LITERAL_IS_THE_POINT.some((a) => file.replace(/\\/g, "/").endsWith(a))) continue;
    // COMMENTS FIRST. `skeleton.tsx` documents its own palette in prose —
    // "slate: #F1F5F9 blocks, #E2E8F0 borders" — and counting that as a raw
    // colour puts a file in the worst list for explaining itself. Three of the
    // first draft's 50 were exactly that. Then strip the arbitrary-value
    // classes, because those are the budget above's population and counting
    // them twice would make one fix move two numbers.
    const src = body.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
    const n = (src.replace(HEX_CLASS, " ").match(RAW_HEX) ?? []).length;
    if (n) { byFile.set(file, n); total += n; }
  }
  const worst = [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  assert.ok(
    total <= HEX_OUTSIDE_A_CLASS_BUDGET,
    `${total} raw hex colours outside a Tailwind class, budget ` +
      `${HEX_OUTSIDE_A_CLASS_BUDGET}. A style={{}} or an SVG attr is the same ` +
      `literal as border-[#…] and drifts the same way — #182350 IS brand and ` +
      `#DC2626 IS red-600, so both have a name.\n  worst: ` +
      worst.map(([f, n]) => `${f} (${n})`).join("\n         "),
  );
  // THE VACUITY FLOOR MOVED RATHER THAN BEING DELETED. It used to read
  // `total >= 1` — "a budget nothing can reach passes for ever" — which was
  // right while the budget was 46 and becomes self-contradictory at 0: the
  // assertion the ratchet exists to reach would fail the moment it was reached.
  //
  // The property it was protecting is that the PROBE still works — that
  // RAW_HEX still matches and the file walk still reads bodies — and the test
  // below already proves exactly that, on the allowlisted files, which hold a
  // literal by construction and always will. So the floor lives there now, and
  // deleting that test silently un-guards this one.
});

test("the allowlist names files that exist and still hold a literal", () => {
  // An allowlist entry for a file that moved, or that no longer has a hex in
  // it, is an exemption nobody is using and a reason nobody can check.
  for (const rel of HEX_LITERAL_IS_THE_POINT) {
    const hit = BODIES.find(({ file }) => file.replace(/\\/g, "/").endsWith(rel));
    assert.ok(hit, `${rel} is allowlisted and does not exist`);
    assert.ok(RAW_HEX.test(hit!.body.replace(HEX_CLASS, " ")),
      `${rel} is allowlisted and holds no raw hex — drop the exemption`);
    RAW_HEX.lastIndex = 0;
  }
});

test("a colour is not written as a raw hex class", () => {
  const { total, byFile } = count(HEX_CLASS);
  const worst = [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  assert.ok(
    total <= HEX_BUDGET,
    `${total} raw hex colour classes, budget ${HEX_BUDGET}. A literal cannot ` +
      `be fixed centrally — when #94A3B8 turned out to render at 2.56:1 the ` +
      `token moved and 1,567 sites did not. Use a token from ` +
      `tailwind.config.ts, and if none fits, add one there.\n  worst: ` +
      worst.map(([f, n]) => `${f} (${n})`).join("\n         "),
  );
});

test("a font size is not written as an arbitrary pixel value", () => {
  const { total, byFile } = count(PX_TEXT);
  const worst = [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  assert.ok(
    total <= PX_TEXT_BUDGET,
    `${total} arbitrary font sizes, and the budget is ${PX_TEXT_BUDGET}: the ` +
      `scale carries every size this product uses. It reaches below ` +
      `Tailwind's smallest — text-3xs is 10px, text-2xs is 11px — and if a ` +
      `step is genuinely missing, add a token in tailwind.config.ts with the ` +
      `reason, do not raise this number.\n  worst: ` +
      worst.map(([f, n]) => `${f} (${n})`).join("\n         "),
  );
});

test("a Tailwind class name is never built by interpolation", () => {
  // The utility prefixes that carry a value Tailwind has to have SEEN. A
  // template hole after one of them is a class that exists only at runtime.
  // THE PREFIX LIST IS DELIBERATELY NARROW. `to-${…}` is a gradient stop AND
  // the middle of `cash-flow-${a}-to-${b}.csv`; `p-`, `m-`, `w-`, `z-` are a
  // single letter before a hyphen and match prose constantly. A guard that
  // cries wolf is a guard somebody deletes, so this matches only prefixes that
  // are not words: the ones that actually carry a colour, a size or a span.
  // A gradient built by interpolation escapes it, and that is the trade — the
  // measured failures here are all colour.
  const BUILT =
    /\b(?:text|bg|border|ring|fill|stroke|divide|shadow|outline|decoration|accent|placeholder|rounded|grid-cols|col-span|row-span|opacity)-\$\{/;
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    // Strip block and line comments first: BankBook.tsx states this very rule
    // in prose and quotes the shape it forbids, and a guard that fails on the
    // documentation of its own rule is a guard nobody keeps.
    const code = body
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
    for (const [i, line] of code.split("\n").entries()) {
      if (BUILT.test(line)) offenders.push(`${file}:${i + 1}  ${line.trim().slice(0, 120)}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `A Tailwind class built by interpolation never reaches the stylesheet — ` +
      `Tailwind scans source text, so the utility is simply absent and the ` +
      `element renders unstyled. Spell each value out and pick between them ` +
      `(components/banking/BankBook.tsx's ALIGN map is the shape).\n  ` +
      offenders.join("\n  "),
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// AND THE TOKEN A SCREEN READS HAS TO BE LEGIBLE
// ─────────────────────────────────────────────────────────────────────────────
// The whole point of migrating 10,030 literals onto the tokens is that a
// colour can then be fixed in ONE place. That cuts both ways: it can also be
// BROKEN in one place, and `ps.hint` spent the product's whole life at
// #94A3B8 — 2.56:1 on white — without anything noticing. Reverting it is a
// one-character edit that no test caught until this one.
//
// WCAG 2.1 SC 1.4.3 wants 4.5:1 for body text. Measured against the two
// grounds a token is actually rendered on: `ps.surface` (#FFFFFF) and the
// application background `ps.bg` (#F8FAFC).
const INK = {
  ink:   "#0D1635",
  body:  "#334155",
  label: "#475569",
  hint:  "#64748B",
  // `disabled` is DELIBERATELY not here. WCAG 1.4.3 exempts text in an
  // inactive control, and darkening it would stop it reading as inactive,
  // which is the one thing that token has to say.
};
const GROUNDS = { "ps.surface": "#FFFFFF", "ps.bg": "#F8FAFC" };

function luminance(hex: string): number {
  const c = hex.replace("#", "");
  const chan = [0, 2, 4].map((i) => {
    const v = parseInt(c.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2];
}
function ratio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const CONFIG = readFileSync("tailwind.config.ts", "utf8");

/** The value the CONFIG holds for an ink step, not a copy of it. A guard that
 *  reads its own table is the Schedule III caption mistake — it passes
 *  whenever both drift together, which is exactly when it is needed. */
function liveInk(name: string): string {
  const m = new RegExp(`\\b${name}:\\s*"(#[0-9A-Fa-f]{6})"`).exec(CONFIG);
  assert.ok(m, `ps.${name} is not declared in tailwind.config.ts any more`);
  return m![1].toUpperCase();
}

test("the ink values recorded here are still the ones the config holds", () => {
  // Its own test, so a moved value fails HERE and does not mask the contrast
  // or ordering checks below — which is what happened the first time this was
  // negative-controlled: collapsing two steps tripped the equality assertion
  // inside the contrast test and the ordering test never ran.
  for (const [name, expected] of Object.entries(INK)) {
    assert.equal(
      liveInk(name), expected.toUpperCase(),
      `ps.${name} moved to ${liveInk(name)}. If that is deliberate, update ` +
        `this table AND say in the token file why — every screen reads it.`,
    );
  }
});

test("every ink token is legible on both grounds", () => {
  const failures: string[] = [];
  for (const name of Object.keys(INK)) {
    const live = liveInk(name);
    for (const [ground, bg] of Object.entries(GROUNDS)) {
      const r = ratio(live, bg);
      if (r < 4.5) failures.push(`ps.${name} ${live} on ${ground} ${bg} = ${r.toFixed(2)}:1`);
    }
  }
  assert.deepEqual(
    failures, [],
    `An ink token below WCAG 1.4.3's 4.5:1. The product writes most of its ` +
      `text at 10px and 11px, so this is not a marginal call.\n  ` +
      failures.join("\n  "),
  );
});

test("the ink scale still has four distinguishable steps", () => {
  // Each step must be visibly darker than the one below it. The four exist so
  // an interactive muted text can darken ONE step on hover and still move —
  // 95 sites in the app take exactly that step. Collapsing two of them makes
  // those hovers silently do nothing, which no screenshot would show.
  const order = ["hint", "label", "body", "ink"];
  for (let i = 1; i < order.length; i++) {
    const lighter = luminance(liveInk(order[i - 1]));
    const darker = luminance(liveInk(order[i]));
    assert.ok(
      darker < lighter,
      `ps.${order[i]} is not darker than ps.${order[i - 1]} — the scale has ` +
        `stopped being a scale and every hover between them is now inert.`,
    );
  }
});

test("the scale reaches below Tailwind's smallest size", () => {
  // 1,860 sites write `text-[10px]` or `text-[11px]`, and T4's job is to
  // rename them. Both steps have to exist for that, and both must stay BARE —
  // a font size and no line-height, which is what `text-[10px]` already emits.
  // Tailwind's tuple form would pin a leading too, and a site nested inside
  // `text-sm` inherits 20px rather than 1.5 × 10px, so pinning one silently
  // changes the rendering of an unknown share of those 1,860 places.
  for (const [name, px] of [["3xs", "10px"], ["2xs", "11px"]]) {
    assert.match(
      CONFIG, new RegExp(`"${name}":\\s*"${px}"`),
      `fontSize.${name} (${px}) is gone from tailwind.config.ts. Without it ` +
        `there is nothing for the arbitrary sizes to be renamed TO, and the ` +
        `budget above can only ever hold — never come down.`,
    );
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// A HOVER HAS TO GO SOMEWHERE
// ─────────────────────────────────────────────────────────────────────────────
// THIS RULE WAS LEARNED BY BREAKING IT. Migrating 10,030 literals onto the
// tokens collapses several spellings onto one name — which is the point — and
// where a hover pair used TWO spellings of one role, both sides land on the
// same token and the hover silently stops doing anything. `#0F172A` and
// `#1E293B` both resolve to the near-black ink, so five dark buttons written
// `bg-[#0F172A] hover:bg-[#1E293B]` came out `bg-brand-dark
// hover:bg-brand-dark` and no longer lightened under the cursor.
//
// The pre-migration check that missed it looked only at `text-` pairs. Three
// more were found by this rule and turned out to PRE-DATE the migration
// entirely — `text-red-600 hover:text-red-600` and friends, dead hovers
// nobody had noticed.
//
// An OPACITY MODIFIER counts as movement: `text-brand hover:text-brand/70` is
// a real hover and the seven sites writing it are correct. The token compared
// therefore includes any `/NN`.
test("no hover lands on the colour it started from", () => {
  const TOKEN = String.raw`([a-z0-9-]+(?:/\d+)?)`;
  const collapsed: string[] = [];
  for (const { file, body } of BODIES) {
    for (const m of body.matchAll(/"[^"]*"/g)) {
      const seg = m[0];
      for (const h of seg.matchAll(new RegExp(`hover:(bg|text|border)-${TOKEN}`, "g"))) {
        const [whole, prop, token] = h;
        const rest = seg.split(whole).join(" ");
        const base = new RegExp(`(?<![\\w:-])${prop}-${token.replace("/", "\\/")}(?![\\w/-])`);
        if (base.test(rest)) collapsed.push(`${file}  ${prop}-${token}`);
      }
    }
  }
  assert.deepEqual(
    [...new Set(collapsed)], [],
    `A hover that resolves to the colour beside it does nothing, and looks ` +
      `exactly like one that works. Pick the step above or below it in the ` +
      `scale.\n  ` + [...new Set(collapsed)].join("\n  "),
  );
});

test("the guards are not vacuous", () => {
  // Each of the three greps must be able to SEE something. A regex that
  // matches nothing passes every budget for ever, which is how a guard quietly
  // stops guarding — this file's own history in CLAUDE.md records four of them.
  assert.ok(FILES.length > 400, `only ${FILES.length} source files scanned`);
  // NOT "the codebase still has some" — that assertion goes vacuous on the
  // day the migration finishes, which is the day the guard matters most.
  // Assert the REGEX works, on a string written here.
  assert.ok(HEX_CLASS.test("border-[#E2E8F0]"), "the hex regex is inert");
  HEX_CLASS.lastIndex = 0;
  assert.ok(PX_TEXT.test("text-[13px]"), "the font-size regex is inert");
  PX_TEXT.lastIndex = 0;
  // And the interpolation regex must match a known-bad line when given one.
  const BUILT =
    /\b(?:text|bg|border)-\$\{/;
  assert.ok(BUILT.test('className={`text-${color}-600`}'), "the interpolation regex is inert");
  // The collapsed-hover rule, on a string written here rather than on the
  // tree — which is clean, so a grep over it proves nothing.
  const probe = '"bg-brand-dark text-white hover:bg-brand-dark"';
  assert.match(probe, /hover:(bg|text|border)-([a-z0-9-]+)/, "the hover regex is inert");
});

// ── A COLOUR THAT MEANS SOMETHING MUST NOT MEAN THE OTHER THING ─────────────
//
// This file's own `money` tokens carry the rule in their comment: "Money
// DIRECTION is its own axis and gets its own tokens, so a figure's colour never
// accidentally says a CA has work to do." That was written about one direction
// of the confusion — a withdrawal painted as a problem. The OTHER direction is
// the same defect and was live: `app/team/page.tsx` painted three error bands
// in `text-money-out` and two READY states (a permission the role is allowed to
// reach, and an Active member chip) in `text-money-in` — a screen with no money
// on it at all, reaching for the money tokens because they were a red and a
// green. An error rendered in the debit colour is exactly what these two axes
// exist to keep apart.
//
// WHAT MAKES IT CHECKABLE IS `role="alert"`. Everywhere else, whether an
// element is a status or a decoration is a judgement and not a regex — T4-b's
// whole difficulty. But an element that declares itself an alert has ANSWERED
// that question, out loud, to a screen reader. So the rule below is asked only
// of those, and it is exact rather than approximate.

/** `role="alert"` and the two lines under it — the band, its icon and its
 *  text. Anything deeper is a judgement again. */
function alertWindows(body: string): string[] {
  const lines = body.split("\n");
  const out: string[] = [];
  lines.forEach((l, i) => {
    if (l.includes('role="alert"')) out.push(lines.slice(i, i + 4).join("\n"));
  });
  return out;
}

const MONEY = /\b(text|bg|border|ring|fill|stroke)-money-(in|out|negative)\b/;
const RAW_STATUS = /\b(text|bg|border)-(red|amber|green|emerald|rose)-\d{2,3}\b/g;

test("a money-direction colour is never a status", () => {
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    for (const w of alertWindows(body)) {
      if (MONEY.test(w)) offenders.push(file);
    }
  }
  assert.deepEqual([...new Set(offenders)], [],
    "an element that declares itself an alert is painted in a money-direction " +
    "token. `money.in`/`money.out` label which way an AMOUNT moved; a failure " +
    "is `state.problem`. See the `money` block in tailwind.config.ts.");
});

test("money direction is used where money has a direction", () => {
  // A location rule stands in for a meaning rule, and the budget is the honest
  // part: today every one of these is in the banking module, which is where an
  // amount has a direction. If another module genuinely shows a debit or a
  // credit, add it here WITH THE REASON rather than raising a number.
  const WHERE_MONEY_MOVES = ["components/banking/"];
  const stray = BODIES
    .filter(({ file }) => !WHERE_MONEY_MOVES.some((p) => file.includes(p)))
    .filter(({ body }) => MONEY.test(body))
    .map(({ file }) => file);
  assert.deepEqual(stray, [],
    "a money-direction token outside the module where money has a direction. " +
    "If this is a STATUS, use `state.*`; if it really is an amount, add the " +
    "path to WHERE_MONEY_MOVES with the reason.");
  // Not vacuous: the tokens are in real use inside that module.
  const inside = BODIES.filter(({ file, body }) =>
    WHERE_MONEY_MOVES.some((p) => file.includes(p)) && MONEY.test(body));
  assert.ok(inside.length >= 5,
    `only ${inside.length} banking files use a money token — the scan is wrong`);
});

test("an element that declares itself an alert carries no raw status colour", () => {
  // The inverse of the rule above, and the reason the conversion was possible
  // at all: `role="alert"` is the one place a scan can be certain the colour
  // is saying something rather than decorating. 59 lines across 29 files were
  // `text-red-600`, `bg-red-100` and `border-red-100` on bands whose SURFACE
  // was already `state.problem-surface` — half-converted, so one error band
  // was two different reds.
  //
  // AND IT IS AN ACCESSIBILITY FIX, WHICH IS NOT WHAT IT LOOKED LIKE. Measured
  // against `state.problem-surface` (#FEF2F2), the surface these bands already
  // used:
  //
  //     text-red-500  #EF4444   3.44:1   FAILS WCAG 1.4.3 (4.5:1)
  //     text-red-600  #DC2626   4.41:1   FAILS, just
  //     state.problem #B91C1C   5.91:1   passes
  //
  // So thirteen `text-red-600` and two `text-red-500` sites were error text —
  // the one message a reader has to read — below the contrast floor, on a
  // surface that was already the token's. One site went the other way and is
  // recorded rather than argued away: `text-red-800` was 7.60:1 and is now
  // 5.91:1, still passing, and one vocabulary is worth the step.
  //
  // ⚠️ AND THE WALK CANNOT SEE ANY OF THIS. An alert band renders only when
  // something has failed, and the smoke walk renders with no data and no
  // errors: 159 of 160 routes came back byte-identical. The verification here
  // is the contrast arithmetic above and the three negative controls below,
  // not a photograph — said plainly, because "no visual diff" would read as
  // evidence when it is the absence of it.
  //
  // ONE PAIR IS EXEMPT AND IT IS THE PAIR, NOT EITHER HALF. A dismiss ✕ is
  // `text-red-400 hover:text-red-600`: no token is light enough for the
  // resting step, and converting only the hover leaves a control that changes
  // HUE under the cursor rather than darkening. So the skip matches the exact
  // pair — a lone `text-red-400` on an alert still fails, which is the case
  // this carve-out must not quietly cover.
  const DISMISS_PAIR = /text-red-400\s+hover:text-red-600/;
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    const code = body.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
    for (const w of alertWindows(code)) {
      const rest = w.replace(DISMISS_PAIR, " ");
      for (const hit of rest.match(RAW_STATUS) ?? []) offenders.push(`${file}: ${hit}`);
    }
  }
  assert.deepEqual(offenders, [],
    "a raw status colour inside an element that announces itself as an alert. " +
    "Use state.problem / state.problem-surface / state.problem-border.");
});

// ── THE SURFACE FOLLOWS THE INK ─────────────────────────────────────────────
//
// T4-b's difficulty is that whether a colour is a STATUS or a decoration is a
// judgement per site. `role="alert"` was the first place that judgement had
// already been made out loud (the rule above). This is the second, and it is
// bigger: **181 class-lists carried `text-state-*` beside a raw Tailwind
// surface** — `bg-red-100 text-state-problem`, `bg-amber-100
// text-state-attention` — because the hex sweep tokenised the INK and left the
// SURFACE where it was. The ink has already declared which of the four states
// this element is in, so the surface is not a judgement any more: it is
// determined by the ink sitting next to it.
//
// It was not cosmetic. The same filing status came out on two different
// grounds across the product — `Filed` was `bg-green-100 text-green-700` on
// the GST and MCA tabs and `bg-emerald-100 text-emerald-700` on GSTR-1 and
// GSTR-3B — and `Overdue` wore three different reds.
//
// WHAT COUNTS AS ONE CLASS-LIST is the whole difficulty of scanning this. A
// ternary — `ok ? "bg-green-50 text-green-700" : "bg-red-100
// text-state-problem"` — is TWO class-lists, and a scan that reads the
// template literal as one unit reports the green branch against the red
// branch's ink. The first version of this scan produced 24 such phantoms. So
// the leaves are: each quoted string, and each static run of a template
// literal between `${` and `}`.

/** The leaf class-lists in one line: quoted strings, and the static runs of a
 *  template literal with its `${...}` holes removed. A ternary's two branches
 *  are two leaves, which is the point. */
function classLeaves(line: string): string[] {
  const out: string[] = [];
  for (const m of line.matchAll(/"([^"\n]*)"|'([^'\n]*)'/g)) out.push(m[1] ?? m[2] ?? "");
  for (const m of line.matchAll(/`([^`\n]*)`/g)) {
    const inner = (m[1] ?? "").replace(/"[^"]*"|'[^']*'/g, " ");
    for (const chunk of inner.split(/\$\{|\}/)) out.push(chunk);
  }
  return out;
}

const PALETTE =
  "red|amber|green|emerald|yellow|orange|rose|blue|gray|slate|indigo|purple|" +
  "violet|teal|cyan|sky|lime|pink|fuchsia|stone|zinc|neutral";
const STATE_INK = /\btext-state-(ready|attention|problem|done)\b/;
const RAW_SURFACE = new RegExp(String.raw`\b(bg|border|ring|divide)-(${PALETTE})-\d{2,3}\b`, "g");
/** Which palette hues ARE that state's own. A `problem` ink on a green surface
 *  is a different kind of wrong from a `problem` ink on red-100, and only the
 *  second is this rule's to fix — so the families are named rather than the
 *  rule saying "any surface". */
const OWN_HUES: Record<string, RegExp> = {
  problem: /^red$/, attention: /^amber$/, ready: /^(emerald|green)$/, done: /^(slate|gray)$/,
};

test("a surface beside a state ink comes from that state", () => {
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    for (const line of body.split("\n")) {
      for (const leaf of classLeaves(line)) {
        const ink = STATE_INK.exec(leaf);
        if (!ink) continue;
        RAW_SURFACE.lastIndex = 0;
        for (const s of leaf.matchAll(RAW_SURFACE)) {
          if (OWN_HUES[ink[1]].test(s[2])) offenders.push(`${file}: ${s[0]} beside ${ink[0]}`);
        }
      }
    }
  }
  assert.deepEqual([...new Set(offenders)], [],
    "a raw palette surface sits beside a state ink that has already said what " +
      "this element is. Use `bg-state-<state>-surface` / " +
      "`border-state-<state>-border`, or `-hover` for a hover fill.\n  " +
      [...new Set(offenders)].join("\n  "));
});

// ── A MONEY TOKEN IS INK IN A CELL, NEVER A PILL ────────────────────────────
//
// The rule above this one — "a money-direction colour is never a status" —
// is asked only of `role="alert"`, and the one below it exempts
// `components/banking/` because that is where an amount genuinely has a
// direction. Between them they left ELEVEN sites uncovered, every one of them
// the defect both rules exist to stop: a `posted` chip, a `completed` chip, an
// "in force" chip, two "✓ the balances agree" notices and a "this mapping
// disagrees" band, all painted `text-money-in` / `text-money-out` because
// those were a green and a red to hand. The carve-out that made the location
// rule safe is exactly what hid them.
//
// What tells the two apart with no judgement: an AMOUNT is ink in a table
// cell and carries no background of its own. Give it a fill and it has become
// a chip or a band, which is a state.
test("a money-direction token carries no surface of its own", () => {
  const ANY_SURFACE = new RegExp(
    String.raw`\b(bg|border|ring|divide)-(?!transparent|current|inherit|white|black)[a-z]+-[a-z0-9-]+`, "g");
  const MONEY_TOKEN = /\b(text|bg|border|ring|fill|stroke)-money-(in|out|negative)\b/;
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    for (const line of body.split("\n")) {
      for (const leaf of classLeaves(line)) {
        if (!MONEY_TOKEN.test(leaf)) continue;
        ANY_SURFACE.lastIndex = 0;
        for (const s of leaf.matchAll(ANY_SURFACE)) offenders.push(`${file}: ${s[0]}`);
      }
    }
  }
  assert.deepEqual([...new Set(offenders)], [],
    "a money-direction token on an element that also has a fill. An amount is " +
      "ink in a cell; once it has a background it is a chip or a band, and " +
      "that is a STATE — use `state.*`.\n  " + [...new Set(offenders)].join("\n  "));
});

// ── A BORDER TOKEN IS A HAIRLINE, NOT A FILL ────────────────────────────────
//
// `state.attention-border` (#FDE68A) is the one value in the state set that
// does NOT carry its own ink: `state.attention` on it is **4.03:1**, under
// WCAG 1.4.3's 4.5. It was being used as a chip fill in three places — the
// `in_progress` reconciliation badge, the `matched` bank-line chip, and the
// Executive role chip on the Team screen, which is a CATEGORY and had no
// business wearing a state token at all.
//
// The fix was not to darken the ink. `ready-hover` already existed and proved
// the shape the set was missing, so `problem-hover` and `attention-hover`
// joined it — and their values are the `-100` steps the product was already
// reaching for, which is why both clear 4.5 (5.30 and 4.51) where the border
// token does not.
test("a state's border token is a border", () => {
  const AS_FILL = /\b(?:[a-z-]+:)?bg-state-[a-z]+-border\b/g;
  const offenders: string[] = [];
  for (const { file, body } of BODIES) {
    for (const m of body.matchAll(AS_FILL)) offenders.push(`${file}: ${m[0]}`);
  }
  assert.deepEqual([...new Set(offenders)], [],
    "`-border` used as a fill. It is the hairline value and does not carry " +
      "the state's own ink: attention-on-attention-border is 4.03:1. Use " +
      "`-surface` for a resting fill and `-hover` under the cursor.\n  " +
      [...new Set(offenders)].join("\n  "));
});

test("the three rules above are not vacuous", () => {
  // Each on a string written HERE, not on the tree — the tree is clean now,
  // so a grep over it proves nothing. This file's own history records four
  // guards that went quietly inert.
  const ternary = 'x ? "bg-green-50 text-green-700" : "bg-red-100 text-state-problem"';
  const leaves = classLeaves(ternary);
  assert.equal(leaves.length, 2, "a ternary must read as TWO class-lists");
  assert.ok(STATE_INK.test(leaves[1]) && !STATE_INK.test(leaves[0]),
    "the ink must be found in the branch that carries it and not the other");
  RAW_SURFACE.lastIndex = 0;
  assert.ok(RAW_SURFACE.test("bg-red-100 text-state-problem"), "the surface regex is inert");
  assert.ok(/\b(bg|border|ring|divide)-(?!transparent|current|inherit|white|black)[a-z]+-[a-z0-9-]+/
    .test("bg-green-100 text-money-in"), "the money-surface regex is inert");
  assert.ok(/\b(?:[a-z-]+:)?bg-state-[a-z]+-border\b/.test("hover:bg-state-attention-border"),
    "the border-as-fill regex is inert");
  // And the token the fix rests on must actually exist in the config.
  for (const t of ["problem-hover", "attention-hover", "ready-hover"]) {
    assert.match(CONFIG, new RegExp(`"${t}"\\s*:`), `state.${t} is missing from the config`);
  }
});
