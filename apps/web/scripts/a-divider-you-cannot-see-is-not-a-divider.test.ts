// A divider drawn fainter than the product's own divider token is not a divider.
// Run with:
//   node --experimental-strip-types --test scripts/a-divider-you-cannot-see-is-not-a-divider.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// 1,009 card headers, table bodies, footers and row separators across 197
// files drew their rule in a colour indistinguishable from the surface behind
// it. On the two surfaces this app actually has — `#FFFFFF` and `ps.bg`
// #F8FAFC — the element is in the DOM, it costs a layout pixel, and nobody can
// see it: a card header sat on top of its own body with nothing between them,
// and a twelve-row table read as one block of text.
//
// IT WAS WRITTEN IN TWO VOCABULARIES AND THE SECOND WAS THE LARGER.
//
//   136  `border-gray-50` 1.02:1 · `border-gray-100` / `border-slate-100` 1.10
//   873  `border-ps-muted` 1.10:1 · `divide-ps-bg` 1.02:1
//
// The second is the one worth reading twice: those are the product's OWN
// tokens — `ps.muted` is the table-header fill and `ps.bg` is the application
// background — used as borders. They came from T3-a (#556), which migrated
// 10,146 hex literals and was RIGHT to be a pure rename: `border-[#F1F5F9]`
// became `border-ps-muted` and nothing moved on screen. What the rename could
// not do is notice that the literal had been invisible all along. So the
// product ended up drawing one element — a card header rule — at three
// different weights depending on which file you opened, and two of the three
// could not be seen.
//
// The product's divider is `ps.border` #E2E8F0 at **1.23:1**, already at 1,722
// sites. So this was never a missing decision — it was 1,009 places that did
// not take the one that exists.
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
// ── BOTH VOCABULARIES, OR THE RULE IS A SPELLING AGAIN ──────────────────────
// The first version of this guard checked the Tailwind families only. It
// passed on a clean tree while 873 `ps-muted` and `ps-bg` edges sat in it —
// six times the population it had just swept — because a guard that knows one
// vocabulary is silently wrong about the other. So `ps.*` is parsed out of the
// token file and measured by the same arithmetic, which also means a token
// added later is covered on the day it is added.
//
// ── THE CARVE-OUT, STATED RATHER THAN LEFT IMPLICIT ─────────────────────────
// Only the NEUTRAL Tailwind families are checked. A neutral divider is drawn
// on a neutral surface by construction, so "contrast on white" is the right
// measurement for it. `border-amber-100` inside an amber callout sits on
// `bg-amber-50`, where the same arithmetic would report a false positive — a
// tinted rule inside a tinted panel is a real thing and is the named-palette
// module pass's business, not this one. The `ps.*` scale needs no such
// carve-out: every one of its values is a neutral.
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

/** Every `ps.*` token, parsed out of the config: `bg: "#F8FAFC"` and friends.
 *
 *  Parsed rather than listed for the reason the bar is: the product's own
 *  scale is the one most likely to gain a value, and a guard that has to be
 *  edited when it does is a guard that will not be. */
const PS_TOKENS: Record<string, string> = Object.fromEntries(
  [...(/\bps:\s*\{([\s\S]*?)\n\s{8}\}/.exec(CONFIG)?.[1] ?? "")
    .matchAll(/"?([a-z-]+)"?:\s*"(#[0-9a-fA-F]{6})"/g)]
    .map((m) => [m[1], m[2]]),
);

/** An edge in the Tailwind vocabulary: `border-b-gray-100`, `divide-y` + `…`. */
const EDGE = new RegExp(
  String.raw`\b(?:border|divide)(?:-[tblrxy])?-(${Object.keys(NEUTRAL_STEPS).join("|")})-(\d{2,3})\b`,
  "g",
);
/** An edge in the product's own: `border-t-ps-muted`, `divide-y divide-ps-bg`. */
const PS_EDGE = /\b(?:border|divide)(?:-[tblrxy])?-ps-([a-z-]+)\b/g;

function offenders(): { file: string; cls: string; ratio: number }[] {
  const found: { file: string; cls: string; ratio: number }[] = [];
  for (const file of ROOTS.flatMap((r) => sources(r))) {
    const body = code(file);
    for (const m of body.matchAll(EDGE)) {
      const hex = NEUTRAL_STEPS[m[1]]?.[m[2]];
      if (!hex) continue; // 300+ — darker than the bar by construction
      const ratio = onWhite(hex);
      if (ratio < BAR) found.push({ file, cls: m[0], ratio });
    }
    for (const m of body.matchAll(PS_EDGE)) {
      const hex = PS_TOKENS[m[1]];
      if (!hex) continue; // not a colour token — `border-ps-border` resolves fine
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

test("the product's own tokens were read out of the config", () => {
  // Non-vacuity for the second vocabulary. An empty map would make the `ps.*`
  // half of this guard inert while every other test still passed — which is
  // exactly what the FIRST version of this file did, by not having the half
  // at all, over a population six times the one it was sweeping.
  assert.ok(
    Object.keys(PS_TOKENS).length > 8,
    `only ${Object.keys(PS_TOKENS).length} ps.* tokens parsed — the config ` +
      "shape moved and the ps half of this guard is checking nothing",
  );
  assert.equal(PS_TOKENS.muted, "#F1F5F9", "ps.muted did not parse");
  assert.equal(PS_TOKENS.border, "#E2E8F0", "ps.border did not parse");
  assert.ok(onWhite(PS_TOKENS.muted) < BAR, "ps.muted must be under the bar");
  assert.ok(onWhite(PS_TOKENS.bg) < BAR, "ps.bg must be under the bar");
});

test("a planted offender is caught in either vocabulary", () => {
  // The negative control for the SCAN. A pattern that quietly stops matching
  // is how four guards in this repository went inert; this one proves it can
  // still see the thing it forbids — in both spellings, because the whole
  // lesson of this file is that one of them is not the other.
  const tailwind = `<div className="border-b border-slate-100" />`;
  assert.equal(
    [...tailwind.matchAll(EDGE)].filter((m) => onWhite(NEUTRAL_STEPS[m[1]][m[2]]) < BAR).length,
    1,
    "the scanner cannot see a planted invisible Tailwind divider",
  );
  const own = `<ul className="divide-y divide-ps-muted" />`;
  assert.equal(
    [...own.matchAll(PS_EDGE)].filter((m) => onWhite(PS_TOKENS[m[1]] ?? "#000") < BAR).length,
    1,
    "the scanner cannot see a planted invisible ps.* divider",
  );
  // And the one it must NOT flag, or the sweep has nowhere to go.
  const ok = `<ul className="divide-y divide-ps-border" />`;
  assert.equal(
    [...ok.matchAll(PS_EDGE)].filter((m) => onWhite(PS_TOKENS[m[1]] ?? "#000") < BAR).length,
    0,
    "the scanner flags the very token it tells people to use",
  );
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
