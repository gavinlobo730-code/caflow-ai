// A divider drawn fainter than the product's own divider token is not a divider.
// Run with:
//   node --experimental-strip-types --test scripts/a-divider-you-cannot-see-is-not-a-divider.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// 129 card headers, table bodies and footers across 50 files drew their rule in
// `border-gray-50` (#F9FAFB) or `border-gray-100` (#F3F4F6). On the two
// surfaces this app actually has — `#FFFFFF` and `ps.bg` #F8FAFC — those are
// **1.02:1** and **1.10:1**. The element is in the DOM, it costs a layout
// pixel, and nobody can see it: a card header sat on top of its own body with
// nothing separating them, and a twelve-row table read as one block of text.
//
// The product's divider is `ps.border` #E2E8F0 at **1.23:1**, already used at
// 1,627 sites. So this was never a missing decision — it was 129 places that
// did not take the one that exists.
//
// ⚠️ THIS IS NOT A WCAG FIX AND MUST NOT BE SOLD AS ONE. 1.4.11 asks 3:1 of a
// component you need in order to understand or operate the interface, and
// `ps.border` does not reach that either. A row divider is not that component;
// what it is, is a mark the designer intended to be visible. The fix is that
// the mark now exists at the weight the rest of the product uses. If a real
// 3:1 divider is ever wanted, it is `ps.border-strong` (#CBD5E1, 1.85:1) and
// it is a design decision, not a sweep.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE IS A CONTRAST, NOT A LIST OF TWO SPELLINGS
// ─────────────────────────────────────────────────────────────────────────────
// `border-gray-50` and `border-gray-100` are two ways of writing this defect
// and `border-slate-100`, `divide-zinc-50` and `border-neutral-100` are three
// more. CLAUDE.md records the lesson four separate guards in this repository
// have had to learn: **write the rule, not a spelling of it.**
//
// So the threshold is COMPUTED, and it is computed from the token file:
// `ps.border`'s own contrast on white. Nothing in this app may draw a divider
// fainter than the product's divider. That has two properties worth having —
// it covers every neutral family and every step without naming them, and if
// somebody darkens `ps.border` the bar rises with it automatically.
//
// ── THE CARVE-OUT, STATED RATHER THAN LEFT IMPLICIT ─────────────────────────
// Only the NEUTRAL families are checked. A neutral divider is drawn on a
// neutral surface by construction, so "contrast on white" is the right
// measurement for it. `border-amber-100` inside an amber callout sits on
// `bg-amber-50`, where the same arithmetic would report a false positive — a
// tinted rule inside a tinted panel is a real thing and is the named-palette
// module pass's business, not this one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOTS = ["app", "components", "lib"];

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

/** Comments stripped, for the reason its neighbour records: "a guard that
 *  fails on the documentation of its own rule is a guard nobody keeps." The
 *  prose above names `border-gray-50` six times. */
function code(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

// ── Contrast ────────────────────────────────────────────────────────────────

/** WCAG 2.x relative luminance. */
function luminance(hex: string): number {
  const n = hex.replace("#", "");
  const ch = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = ch.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

/** WCAG 2.x contrast ratio against white. */
function onWhite(hex: string): number {
  return 1.05 / (luminance(hex) + 0.05);
}

// ── The bar, read out of the token file ─────────────────────────────────────
//
// Read rather than restated: a second copy of #E2E8F0 here is a second
// authority on what the product's divider is, and this repository has recorded
// what happens when a browser-side copy of a vocabulary drifts from the one
// that owns it.
const CONFIG = readFileSync("tailwind.config.ts", "utf8");
const PS_BORDER = /\bborder:\s*"(#[0-9a-fA-F]{6})"/.exec(CONFIG)?.[1];

test("the bar is read out of the token file, not restated here", () => {
  assert.ok(
    PS_BORDER,
    "could not find `ps.border` in tailwind.config.ts — this guard has no bar " +
      "and would pass on everything. Fix the parse, never delete the assertion.",
  );
});

const BAR = onWhite(PS_BORDER ?? "#E2E8F0");

// ── The neutral ramps ───────────────────────────────────────────────────────
//
// Tailwind's own default values. Only the steps light enough to be in question
// are held: everything at 300 and above is unambiguously darker than the bar,
// and listing the whole ramp would invite somebody to "correct" a value that
// is never read.
const NEUTRAL_STEPS: Record<string, Record<string, string>> = {
  gray:    { "50": "#F9FAFB", "100": "#F3F4F6", "200": "#E5E7EB" },
  slate:   { "50": "#F8FAFC", "100": "#F1F5F9", "200": "#E2E8F0" },
  zinc:    { "50": "#FAFAFA", "100": "#F4F4F5", "200": "#E4E4E7" },
  neutral: { "50": "#FAFAFA", "100": "#F5F5F5", "200": "#E5E5E5" },
  stone:   { "50": "#FAFAF9", "100": "#F5F5F4", "200": "#E7E5E4" },
};

/** An edge: `border-b-gray-100`, `border-gray-50`, `divide-y` + `divide-…`. */
const EDGE = new RegExp(
  String.raw`\b(?:border|divide)(?:-[tblrxy])?-(${Object.keys(NEUTRAL_STEPS).join("|")})-(\d{2,3})\b`,
  "g",
);

function offenders(): { file: string; cls: string; ratio: number }[] {
  const found: { file: string; cls: string; ratio: number }[] = [];
  for (const file of ROOTS.flatMap((r) => sources(r))) {
    for (const m of code(file).matchAll(EDGE)) {
      const hex = NEUTRAL_STEPS[m[1]]?.[m[2]];
      if (!hex) continue; // 300+ — darker than the bar by construction
      const ratio = onWhite(hex);
      if (ratio < BAR) found.push({ file, cls: m[0], ratio });
    }
  }
  return found;
}

// ── The tests ───────────────────────────────────────────────────────────────

test("the scan reads files at all", () => {
  const files = ROOTS.flatMap((r) => sources(r));
  assert.ok(files.length > 400, `only ${files.length} sources walked`);
  // Non-vacuity on the REGEX as well as on the file walk: an edge class that
  // passes must still be FOUND, or a broken pattern reads as a clean tree.
  const seen = files.filter((f) => EDGE.test(code(f))).length;
  assert.ok(seen > 0, "the edge pattern matched nothing anywhere — it is broken");
});

test("the threshold ranks known values the way the prose says", () => {
  // The negative control for the arithmetic itself. If `luminance` were wrong,
  // every ratio would be wrong together and the sweep would still "pass".
  assert.ok(Math.abs(onWhite("#FFFFFF") - 1) < 0.001, "white against white is 1:1");
  assert.ok(Math.abs(onWhite("#000000") - 21) < 0.05, "black against white is 21:1");
  assert.ok(onWhite("#F9FAFB") < BAR, "gray-50 must be under the bar");
  assert.ok(onWhite("#F3F4F6") < BAR, "gray-100 must be under the bar");
  assert.ok(onWhite("#E5E7EB") >= BAR, "gray-200 must clear it");
  assert.ok(onWhite("#CBD5E1") > BAR, "ps.border-strong must clear it comfortably");
});

test("a planted offender is caught", () => {
  // The negative control for the SCAN. A pattern that quietly stops matching
  // is how four guards in this repository went inert; this one proves it can
  // still see the thing it forbids.
  const probe = `<div className="border-b border-slate-100" />`;
  const hits = [...probe.matchAll(EDGE)].filter(
    (m) => onWhite(NEUTRAL_STEPS[m[1]][m[2]]) < BAR,
  );
  assert.equal(hits.length, 1, "the scanner cannot see a planted invisible divider");
});

test("no divider is fainter than the product's own divider token", () => {
  const found = offenders();
  assert.deepEqual(
    found.map((f) => `${f.file}: ${f.cls} (${f.ratio.toFixed(2)}:1)`),
    [],
    `these edges are drawn fainter than ps.border (${BAR.toFixed(2)}:1 on ` +
      "white), so they occupy a pixel and show nothing. Use `border-ps-border` " +
      "— or `border-ps-border-strong` where the rule is load-bearing.",
  );
});
