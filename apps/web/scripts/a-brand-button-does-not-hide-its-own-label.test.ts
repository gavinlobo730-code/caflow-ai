// apex-overview-practice-05: a `bg-brand` button (dark navy) combined with a
// dark label colour (`text-gray-900`/`text-slate-900`/`text-ps-ink` and
// friends) renders essentially invisible text — dark on dark. Three call
// sites had it (TaskFormModal's "Create Task", ClientFormModal's "Add
// Client"/"Save Changes", CsvImportModal's "Import N rows"), each next to a
// SIBLING button in the same file using the correct `text-white`, which is
// what makes this a copy-paste contrast bug rather than three independent
// design choices.
//
// This is the systemic guard, not a fix for the three sites: a class string
// combining a light background token with a dark-900-scale text token is
// wrong on ANY button, in ANY file, so the check walks the whole tree rather
// than naming files.
//
// LINE-BASED, DELIBERATELY, NOT A QUOTE PARSER. A first version tried to
// extract the actual quoted class STRING with a `["'\`]...["'\`]` regex —
// which breaks the moment a comment anywhere in the same file contains an
// English contraction ("can't", "doesn't", "client's": an apostrophe that
// opens a "string" closed only by the next quote-like character anywhere
// after it, silently mis-pairing every real string that follows). Real
// Tailwind `className="…"` attributes are written on one physical line in
// this codebase (every offender found so far is), so matching per LINE
// avoids the whole class of quote-pairing bugs a real parser would need to
// solve properly.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const WEB = path.resolve(import.meta.dirname, "..");
const ROOTS = ["app", "components", "lib"];

function allSourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
        walk(full);
      } else if (/\.(tsx|ts)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
        out.push(full);
      }
    }
  };
  for (const r of ROOTS) {
    const p = path.join(WEB, r);
    if (fs.existsSync(p)) walk(p);
  }
  return out;
}

// A bare `bg-brand` (the dark navy surface) — NOT `bg-brand/NN` (a tint,
// near-white at low opacities), `bg-brand-dark` or `bg-brand-light` (both
// different tokens) — in the SAME class string as a 900-scale dark text
// token, in EITHER order (`bg-brand … text-gray-900` or `text-gray-900 …
// bg-brand`).
const DARK_TEXT = "text-(?:gray|slate|zinc|neutral)-9\\d\\d\\b|text-ps-ink\\b";
const BRAND_THEN_DARK = new RegExp(`\\bbg-brand\\b(?!/|-dark|-light)[^\\n]*\\b(?:${DARK_TEXT})`);
const DARK_THEN_BRAND = new RegExp(`\\b(?:${DARK_TEXT})[^\\n]*\\bbg-brand\\b(?!/|-dark|-light)`);

function isOffendingString(s: string): boolean {
  return BRAND_THEN_DARK.test(s) || DARK_THEN_BRAND.test(s);
}

// The quoted substrings on ONE line — restricted to a single line
// deliberately (see the header): a line is short enough that its quotes
// reliably pair with their OWN kind, so `"can't"` two lines above never
// reaches here, and a conditional like
//   tab === t.id ? "bg-brand text-white" : "text-ps-ink hover:bg-ps-bg"
// is read as TWO SEPARATE strings rather than one line-wide blob — which
// matters, because that example is not a bug: bg-brand and the dark text
// apply in DIFFERENT branches and are never on the element together. An
// earlier, whole-line version of this check flagged exactly that ternary
// shape in three real files as a false positive.
function quotedSegmentsIn(line: string): string[] {
  const out: string[] = [];
  for (const re of [/"([^"]*)"/g, /'([^']*)'/g, /`([^`]*)`/g]) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(line))) out.push(m[1]);
  }
  return out;
}

function isOffendingLine(line: string): boolean {
  return quotedSegmentsIn(line).some(isOffendingString);
}

test("no class string pairs a solid bg-brand surface with a dark-900 text colour", () => {
  const offenders: string[] = [];
  for (const file of allSourceFiles()) {
    const lines = fs.readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const seg of quotedSegmentsIn(line)) {
        if (isOffendingString(seg)) {
          offenders.push(`${path.relative(WEB, file)}:${i + 1}: "${seg}"`);
        }
      }
    });
  }
  assert.deepEqual(offenders, [],
    "a bg-brand element's own label is set to a dark-900 text colour, which " +
    "is dark text on a dark background:\n" + offenders.join("\n"));
});

test("negative control: the detector actually fires on the original three sites' pattern", () => {
  assert.ok(isOffendingLine(
    '              className="flex-1 rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-gray-900 hover:bg-brand-dark disabled:opacity-60"'));
  assert.ok(isOffendingLine(
    '              className="px-5 py-2 bg-brand text-gray-900 text-sm font-medium rounded-lg hover:bg-brand-dark"'));
  assert.ok(isOffendingLine(
    '              className="flex-1 rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-gray-900 hover:bg-brand-dark disabled:opacity-60 disabled:cursor-not-allowed"'));
});

test("negative control: a tinted bg-brand/5 with text-ps-ink is NOT flagged (IffPanel's selected-tab style)", () => {
  assert.ok(!isOffendingLine('              ? "border-brand bg-brand/5 text-ps-ink font-medium"'),
    "a 5% tint is near-white and text-ps-ink is the right pairing on it");
});

test("negative control: bg-brand with text-white is NOT flagged (the sibling button in the same files)", () => {
  assert.ok(!isOffendingLine(
    '              className="px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark"'));
});

test("negative control: an unrelated apostrophe elsewhere in the file cannot suppress a real offender", () => {
  // Regression guard for the quote-pairing bug the header describes: an
  // English contraction on an EARLIER line must not swallow a real
  // offending className on a LATER line, because per-line matching never
  // looks across lines at all.
  const contraction = "// that's what makes a newly-created entity disappear";
  const offender = '              className="bg-brand text-gray-900"';
  assert.ok(!isOffendingLine(contraction));
  assert.ok(isOffendingLine(offender));
});
