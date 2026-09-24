// A rupee figure is formatted by `lib/money/format`, and nowhere else builds one.
//   node --experimental-strip-types --test scripts/a-rupee-figure-is-formatted-in-one-place.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// Measured on 18 September 2026 across `app/`, `components/` and `lib/`: **248
// money formatters in 26 distinct behaviours**. The plan's own estimate was 53
// in 11, made with a narrower pattern.
//
// What the spread cost:
//
//   * **139 had no `en-IN` locale**, so they grouped the WESTERN way
//     (₹1,234,567) or not at all, against decision D6 — Indian grouping
//     everywhere, 12,34,567, never 1,234,567.
//   * about **150 were null-unsafe**. The shared one 73 files import rendered
//     `undefined` as the literal **"₹NaN"** and `null` as **"₹0.00"** — the
//     second worse than the first, because a figure nobody holds was shown as
//     one somebody computed, which is the distinction this codebase makes
//     load-bearing everywhere else.
//   * the whole-rupee one **ROUNDED**, so ₹1,23,456.50 came out ₹1,23,457 — a
//     second implementation of a rounding rule, disagreeing with CGST §170
//     (`domain/gst/money.py`) at exactly the value it is most often asked
//     about.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, AND WHY IT IS THIS ONE AND NOT THE OBVIOUS ONE
// ─────────────────────────────────────────────────────────────────────────────
// The obvious rule — "no `(paise / 100)` outside the module" — would be wrong,
// and measurably so: 103 sites divide by 100 and `toFixed(2)`, and a large
// share of them are CSV CELLS and `<input value>` strings, which must NOT carry
// a ₹ or a comma. Banning the division would push those toward the formatter
// and produce broken exports. That population needs reading one at a time.
//
// What IS certain is the CONSTRUCTION: an `Intl.NumberFormat` with
// `currency: "INR"` is a rendering rule, and a second one is a second answer to
// D5 and D6. There were six, in five files; there are now two, both inside
// `lib/money/format.ts`. A seventh cannot appear.
//
// The budget below is the second half, and it ratchets — a ban would fail on
// the first commit and stay failing, which is not a line anybody holds.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOTS = ["app", "components", "lib"];
/** The one module allowed to construct a rupee rendering. */
const AUTHORITY = join("lib", "money", "format.ts");

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

/** `currency: "INR"` — an Intl rupee rendering rule, however it is spelled.
 *
 *  DELIBERATELY NOT `/g`. A global regex carries `lastIndex` between calls, so
 *  `assert.match` and `assert.doesNotMatch` mutate it and the NEXT assertion
 *  starts scanning from wherever the last one stopped — which makes a guard
 *  pass or fail depending on the order its own tests ran in. A negative
 *  control caught exactly that here: reverting the delegation failed three
 *  tests instead of one, and the third was this. `countIn` builds a fresh
 *  global copy per call, which is the only place one is needed. */
const INR_FORMAT = /currency:\s*["']INR["']/;

/** How many times a pattern occurs, without sharing state with anybody. */
function countIn(body: string, re: RegExp): number {
  return (body.match(new RegExp(re.source, "g")) ?? []).length;
}

test("only lib/money/format constructs a rupee rendering", () => {
  const elsewhere: string[] = [];
  for (const { file, body } of BODIES) {
    if (file === AUTHORITY) continue;
    const n = countIn(body, INR_FORMAT);
    if (n) elsewhere.push(`${file} (${n})`);
  }
  assert.deepEqual(
    elsewhere,
    [],
    `A second Intl rupee formatter is a second answer to D5 (two decimals) ` +
      `and D6 (Indian grouping), and the six that existed gave four different ` +
      `ones. Import from lib/money/format: formatPaise, formatWhole, ` +
      `formatPaiseBare.\n  ` + elsewhere.join("\n  "),
  );
});

test("the multi-currency formatter is NOT this rule", () => {
  // `lib/services/formatting.formatMoney` renders ANY ISO currency in minor
  // units (Multi-Currency Phase 5) and takes its code as a parameter, so it
  // never writes `currency: "INR"` and is untouched by the rule above. It is
  // named here so the next reader does not fold the two together: a USD
  // receivable is not a rupee figure and does not take D5's two decimals by
  // Indian convention — it takes its own currency's exponent.
  const formatting = BODIES.find((b) => b.file.endsWith(join("services", "formatting.ts")));
  assert.ok(formatting, "lib/services/formatting.ts has moved");
  assert.match(formatting!.body, /formatMoney/, "the multi-currency formatter is gone");
  assert.doesNotMatch(
    formatting!.body,
    INR_FORMAT,
    "formatting.ts builds a rupee formatter again — it should delegate",
  );
});

// ── The budget ──────────────────────────────────────────────────────────────
//
// Every function whose NAME says it renders money and whose body touches paise
// or divides by 100. LOWER THIS as screens move onto the authority; never
// raise it.
//
//   18 Sep 2026, measured: 257 formatters in 26 behaviours (the classifier here
//   is slightly wider than the one that reported 248 — it counts the new
//   module's own exports and its tests, which is right: they are formatters)
//   18 Sep 2026, after the four Intl strays were delegated: unchanged — the
//   spread is in the per-screen `fmt()` helpers, and moving those is T4.
//   24 Sep 2026: 257 -> 115, and NOT because anything moved. The `const` limb
//   was matching any VALUE whose name ends in `Paise` — including
//   `const openingBalancePaise = paiseFromRupeeInput(...)`, which is a parsed
//   value produced by the very authority this file pushes people towards, and
//   is the opposite of a per-screen formatter. 142 of the 257 were that. The
//   matcher now requires the right-hand side to BE a function, and the budget
//   is the real figure. Lowering it on a corrected measurement is the ratchet
//   working; raising it is not.
// Non-global for the same reason; `moneyFormatters` makes its own copy.
// A FUNCTION, not any value whose name ends in `Paise`.
//
// The `const` limb used to match a bare assignment, so
// `const creditLimitPaise = paiseFromRupeeInput(input)` — a PARSED VALUE, the
// opposite of a per-screen formatter, and produced by the one authority this
// file exists to push people towards — counted as a formatter and pushed the
// total over budget. The rule is "a function whose name says it renders
// money"; this now says that, by requiring the right-hand side to BE a
// function (`(args) =>`, `arg =>`, `function`, or `async` either way).
const MONEY_FN =
  /(?:export\s+)?(?:function\s+(\w*(?:fmt|format|rupee|money|inr|paise|currency)\w*)\s*\(|const\s+(\w*(?:fmt|format|rupee|money|inr|paise|currency)\w*)\s*=\s*(?:async\s+)?(?:function\b|\(|[A-Za-z_$][\w$]*\s*=>))/i;
const NOT_MONEY = /date|day|time|period|label|name|qty|quantity|percent|pct|bps|size|dur/i;
const FORMATTER_BUDGET = 115;

function moneyFormatters(): string[] {
  const found: string[] = [];
  for (const { file, body } of BODIES) {
    for (const m of body.matchAll(new RegExp(MONEY_FN.source, "gi"))) {
      const name = m[1] ?? m[2];
      if (!name || NOT_MONEY.test(name)) continue;
      const chunk = body.slice(m.index!, m.index! + 420);
      if (!/paise/i.test(chunk) && !/\/ ?100/.test(chunk)) continue;
      found.push(`${file}:${name}`);
    }
  }
  return found;
}

test("the number of money formatters does not grow", () => {
  const found = moneyFormatters();
  assert.ok(
    found.length <= FORMATTER_BUDGET,
    `${found.length} money formatters, budget ${FORMATTER_BUDGET}. 26 ` +
      `different behaviours is what a set this size produced. Import from ` +
      `lib/money/format rather than writing a per-screen fmt().`,
  );
});

test("the guards are not vacuous", () => {
  assert.ok(FILES.length > 400, `only ${FILES.length} source files scanned`);
  // Each regex must match a string written HERE, not merely find nothing in a
  // tree that is clean — the assertion that goes inert on the day it matters.
  assert.match('currency: "INR",', INR_FORMAT);
  assert.match("function fmtPaise(p: number)", MONEY_FN);
  assert.ok(moneyFormatters().length > 50, "the formatter scan matches almost nothing");
  // And the authority must actually be the authority.
  const auth = BODIES.find((b) => b.file === AUTHORITY);
  assert.ok(auth, "lib/money/format.ts is missing");
  assert.match(auth!.body, INR_FORMAT, "the authority builds no rupee formatter");
});
