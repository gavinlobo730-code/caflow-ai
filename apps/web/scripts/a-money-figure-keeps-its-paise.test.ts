/**
 * A MONEY FIGURE SHOWN TO A HUMAN KEEPS ITS PAISE, AND GROUPS THE INDIAN WAY.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * `(paise / 100).toLocaleString("en-IN")` looks like the right thing and is
 * not. With no options, `Intl` defaults to `minimumFractionDigits: 0` and
 * `maximumFractionDigits: 3`, so:
 *
 *     ₹1,18,000.50  →  "1,18,000.5"     one decimal, which reads as a typo
 *     ₹1,18,000.00  →  "1,18,000"       and the neighbouring row shows .5
 *
 * and with `Math.floor` or `Math.trunc` in front of it the paise are simply
 * gone. A column where some rows carry paise and some do not cannot be added
 * up by eye, which is the whole job of a statutory table. Decision D5 says two
 * decimals; `lib/money/format.ts` is the authority and its own header sets out
 * why (a browser-side ROUND would be a second implementation of CGST §170).
 *
 * On 19 September 2026 this reached 20 sites in 16 files, most of them a
 * per-file `rupees()` / `fmt()` helper, so one wrong helper was every figure on
 * its screen: the ITC register (the credit claimed on a return), the §37(3)
 * amendment panel, the payroll drawer and the client payroll page, the GST and
 * TDS compliance tabs, engagements, the loan risk register and both party
 * lookups.
 *
 * ── AND THE SAME SWEEP FOUND THE TRIAL BALANCE'S OWN TOTAL ──────────────────
 * The rows went through `formatPaise` and the FOOTER did `(x/100).toFixed(2)`,
 * so the one line a CA reads to check that the two sides agree grouped
 * WESTERN — ₹123456.78 under a column of ₹1,23,456.78.
 *
 * ── WHAT IS DELIBERATELY NOT FORBIDDEN ──────────────────────────────────────
 * `toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits:
 * 2 })` produces the right string. It is still the formatter written out
 * again, and moving those is T4's adoption pass — but it is not a wrong
 * figure, and a guard that fails on a correct render teaches people to
 * disable it.
 *
 * A CSV cell and an `<input value>` must NOT carry a ₹ or a grouping comma,
 * which is why this rule is about the OPTIONS and not about "divides by 100":
 * 87 of the sites that divide by 100 are exactly those, and a sweep over them
 * would have broken seven CSV exports whose header — `"Budget (₹)"` — carries
 * the glyph while the cell must not.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e);
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx") || rel.endsWith(".ts")) out.push(rel);
  }
  return out;
}
const FILES = [...walk("app"), ...walk("components"), ...walk("lib")];

/** Comments first — this file's own prose contains the defect it forbids. */
function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

/** A paise figure handed to `toLocaleString` with NO options. The `/ 100` is
 *  what makes it money rather than a count of invoices. */
const DROPS_PAISE = /\/\s*100\s*\)?\s*\)?\.toLocaleString\(\s*"en-IN"\s*\)/g;
/** A rupee figure hand-formatted to two decimals in JSX, next to the glyph. */
const UNGROUPED = /₹\s*\{[^}]*\.toFixed\(/g;

function hits(rx: RegExp): string[] {
  const out: string[] = [];
  for (const f of FILES) {
    for (const _ of code(f).matchAll(rx)) out.push(f);
  }
  return out;
}

test("no money figure is rendered with its paise dropped", () => {
  const found = hits(DROPS_PAISE);
  assert.deepEqual(found, [],
    'toLocaleString("en-IN") with no options renders ₹1,18,000.50 as ' +
    '"1,18,000.5". Use formatPaise / formatPaiseBare from lib/money/format, ' +
    "or pass { minimumFractionDigits: 2, maximumFractionDigits: 2 }:\n  " +
    [...new Set(found)].join("\n  "));
});

test("no money figure is rendered ungrouped beside a rupee glyph", () => {
  const found = hits(UNGROUPED);
  assert.deepEqual(found, [],
    "₹{(x/100).toFixed(2)} groups the WESTERN way — ₹123456.78 against D6's " +
    "₹1,23,456.78. formatPaise emits the glyph itself:\n  " +
    [...new Set(found)].join("\n  "));
});

test("the two probes are about real shapes, not empty regexes", () => {
  // Each pattern must still match its own defect, or both tests above pass on
  // a tree full of it — which is exactly how the money-formatter guard passed
  // before. Asserted against a string built here, so no file has to keep one.
  const bad = 'x = `₹${(p / 100).toLocaleString("en-IN")}`';
  const ungrouped = "<td>₹{(total/100).toFixed(2)}</td>";
  assert.ok(new RegExp(DROPS_PAISE.source).test(bad));
  assert.ok(new RegExp(UNGROUPED.source).test(ungrouped));
  // And the deliberate carve-out must NOT match, or the rule bans a correct
  // render and somebody disables it.
  const fine = 'y = (p / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })';
  assert.ok(!new RegExp(DROPS_PAISE.source).test(fine));
});

test("the authority still says two decimals — in EVERY formatter it holds", () => {
  // COUNTED, not matched once. The module builds three `Intl.NumberFormat`s
  // and only one of them is allowed to round (`formatWhole`, which takes a
  // figure the SERVER has already rounded under CGST §170). A `match` anywhere
  // in the file passes with the main formatter set to 0 decimals and the bare
  // one still at 2, which is the defect this whole guard is about.
  const fmt = code("lib/money/format.ts");
  const ctors = [...fmt.matchAll(/new Intl\.NumberFormat\("en-IN",\s*\{[^}]*\}/g)]
    .map((m) => m[0]);
  assert.ok(ctors.length >= 3,
    `only ${ctors.length} en-IN formatters found in the authority — it has been ` +
    "restructured and this guard no longer sees what it is asserting");
  const twoDecimals = ctors.filter((c) => /minimumFractionDigits:\s*2/.test(c)
    && /maximumFractionDigits:\s*2/.test(c));
  assert.ok(twoDecimals.length >= ctors.length - 1,
    "every formatter but the whole-rupee one must pin two decimals (D5); " +
    `${ctors.length - twoDecimals.length} do not`);
});
