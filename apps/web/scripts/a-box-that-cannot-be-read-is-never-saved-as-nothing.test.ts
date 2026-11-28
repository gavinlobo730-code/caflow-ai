// POST-A-571 / POST-A-569 — a form never reads the reader's refusal as nothing.
//
// WHY THIS EXISTS
//     `paiseFromRupeeInput`, `bpsFromPercentInput` and `parseQuantity` answer null for text that is not what the box takes. A caller that
//     writes `reader(text) ?? 0` (or `?? 1` for a quantity) turns that refusal into a figure nobody typed and carries on. Three were live:
//     a full-and-final settlement recorded "12,50" of notice pay as none recovered and posted it; a salary revision, a loan, a perquisite
//     valuation and an arrears worksheet did the same in the employee drawer; the CMP-08 panel prepared a statement without unreadable
//     interest; the GSTR-4 panel saved a rate of "1,8" as 0 per cent; a quotation or order line became quantity 1 at a rate of nothing.
//
// THE RULE
//     A file that defaults a reader's refusal asks `unreadableBoxesSentence` (lib/money/rupeeInput.ts) first, or is on the list below with
//     the reason the default cannot be reached with unreadable text. The list only shrinks: an entry whose file no longer defaults fails.
//     File by file, not function by function: the scan cannot see which function a default sits in, so a file that asks once and defaults in
//     a second form it never asks about would pass. Each file here was read; the settlement drawer has its own function-level test.
//
//   node --experimental-strip-types --test scripts/a-box-that-cannot-be-read-is-never-saved-as-nothing.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const DEFAULTED = /(paiseFromRupeeInput|bpsFromPercentInput|parseQuantity)\([^()]*(?:\([^()]*\))?[^()]*\)\s*\?\?\s*[01]\b/;

/** Files that default a reader's refusal and do not ask, each with why the default cannot be reached with text that is typed and unreadable. */
const DEFAULT_IS_UNREACHABLE: Record<string, string> = {
  "app/clients/[id]/tax/computation/page.tsx":
    "the compute refuses every box by name at its top (the list of [label, text] pairs) before these lines run",
  "app/income-tax/advance-tax/page.tsx":
    "the estimated-tax box is a number box, which cannot hold text that is not a number, and a nil estimate computes nothing",
  "app/income-tax/capital-gains/page.tsx":
    "the register's and the claim's amount boxes are number boxes; the calculator's text boxes are refused by amountsUnreadable",
  "components/invoices/InvoiceEditor.tsx":
    "the cess-per-unit box is a number box, and this line only draws the Amount cell",
  "components/payroll/ApplyStructureModal.tsx":
    "a gross that reads as nothing is 'missing' and holds both Preview and Apply (missingGross)",
};

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
      sourceFiles(rel, found);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
      found.push(rel.split(path.sep).join("/"));
    }
  }
  return found;
}

const code = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const defaulting = ["app", "components", "lib"].flatMap((d) => sourceFiles(d)).filter((rel) => DEFAULTED.test(code(rel)));

test("the scan finds the files that default a reader's refusal", () => {
  assert.ok(defaulting.length >= 6, `only ${defaulting.length} files found: the scan has stopped seeing the pattern`);
  assert.ok(defaulting.includes("components/payroll/EmployeeDrawer.tsx"));
});

test("a file that defaults a reader's refusal asks which boxes cannot be read first, or says why the default cannot be reached", () => {
  const silent = defaulting.filter((rel) => !code(rel).includes("unreadableBoxesSentence(") && !(rel in DEFAULT_IS_UNREACHABLE));
  assert.deepEqual(silent, [], "these files read text a person typed, default the reader's refusal to 0 or 1, and never ask whether the text could be read");
});

test("an entry on the list is still a file that defaults and does not ask", () => {
  for (const rel of Object.keys(DEFAULT_IS_UNREACHABLE)) {
    assert.ok(defaulting.includes(rel), `${rel} no longer defaults a reader's refusal: take it off the list`);
    assert.ok(!code(rel).includes("unreadableBoxesSentence("), `${rel} asks now: take it off the list`);
  }
});

test("the rule can fail", () => {
  assert.ok(DEFAULTED.test('basic_paise: paiseFromRupeeInput(basic) ?? 0,'));
  assert.ok(DEFAULTED.test('quantity: parseQuantity(l.quantity) ?? 1,'));
  assert.ok(DEFAULTED.test('x: (bpsFromPercentInput(form.rate.trim()) ?? 0) / 100'));
  assert.ok(!DEFAULTED.test('average: paiseFromRupeeInput(averageTenMonths),'), "a reader whose null is passed on as null is not a default");
});

// POST-A-570 — nobody takes the commas out of an amount before the reader sees it. About twenty callers did (`.replace(/[,\s₹]/g, "")`), so a
// comma in a place nobody writes one was removed and 1,2,5 was read as 125 (and, before a percentage, 1,0 as 10 per cent). The reader reads proper
// grouping itself and refuses the rest; a caller may still take off the rupee sign, a percent sign and spaces.
test("no caller removes commas from text it then hands to a reader", () => {
  const STRIPS = /\.replace\(\/[^/\n]*,[^/\n]*\/g?,\s*""\)/;
  const offenders = ["app", "components", "lib"].flatMap((d) => sourceFiles(d))
    .filter((rel) => rel !== "lib/money/rupeeInput.ts" && STRIPS.test(code(rel)));
  assert.deepEqual(offenders, [], "these files remove commas themselves: leave them for lib/money/rupeeInput.ts, which reads grouping and refuses a misplaced comma");
  assert.ok(STRIPS.test('paiseFromRupeeInput(raw.replace(/[,\\s₹]/g, ""))'), "the pattern no longer sees the shape it was written for");
  assert.ok(!STRIPS.test('raw.replace(/[\\s₹]/g, "")'));
});

