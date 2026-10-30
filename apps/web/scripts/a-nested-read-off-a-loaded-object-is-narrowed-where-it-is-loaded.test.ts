/**
 * The reads `x && x.a.b` that the payload guards could not see, narrowed where the object is LOADED (POST-A-149).
 *
 * `an-object-payload-is-not-its-fields-until-it-is-checked` follows object STATE that is set straight from `.data`. It cannot
 * follow a value a helper returns, or a prop a page hands down, and the smoke walk of 16-09-2026 (13 screens) was exactly a
 * nested field read off a payload that lacked it. The reads that remained were of the form `existing && existing.lines.length`,
 * where the root is guarded and the field is not: `{}` is truthy, so the guard passes it and the read throws.
 *
 * WHAT IS FIXED, AND WHERE: not at the thirty reads, at the NINE places the objects come from. The six document detail loaders
 * and the six duplicate seeds the editors take (`existing`, `duplicateSeed`) return a detail only if it has its `lines`; the TDS
 * deduction preview refuses an answer without its `explain`; the TDS deposit state needs its `warnings` list and its two maps; the
 * capital-gains exemption working needs its three lists; the fixed-asset categories keep a category with no classes as one with
 * an empty list; the statement preview needs its `balance_check`. A read added next year is covered without anybody remembering,
 * which is the argument `lib/api/shape.ts` makes for narrowing at the setter.
 *
 * WHAT THIS PINS. That each of those sources still narrows, by the helper it narrows with. It does not prove a read elsewhere is
 * safe, and it is not a general rule over helper-returned values (that would need a data-flow walk this repository does not have;
 * the ledger line says so). The population of `x && x.a.b` reads is counted so a vacuous walk fails.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke"]);

function read(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n").map((l) => l.replace(/\/\/.*$/, "")).join("\n");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

const DETAILS: [string, string][] = [
  ["lib/invoices/editorContext.ts", "InvoiceDetail"],
  ["lib/purchases/editorContext.ts", "PurchaseBillDetail"],
  ["lib/sales/salesCreditNoteEditorContext.ts", "SalesCreditNoteDetail"],
  ["lib/sales/salesDebitNoteEditorContext.ts", "SalesDebitNoteDetail"],
  ["lib/purchases/debitNoteEditorContext.ts", "DebitNoteDetail"],
  ["lib/purchases/purchaseCreditNoteEditorContext.ts", "PurchaseCreditNoteDetail"],
];
const SEEDS: [string, string][] = [
  ["lib/invoices/duplicateSeed.ts", "InvoiceDetail"],
  ["lib/purchases/duplicateSeed.ts", "PurchaseBillDetail"],
  ["lib/sales/salesCreditNoteDuplicateSeed.ts", "SalesCreditNoteDetail"],
  ["lib/sales/salesDebitNoteDuplicateSeed.ts", "SalesDebitNoteDetail"],
  ["lib/purchases/debitNoteDuplicateSeed.ts", "DebitNoteDetail"],
  ["lib/purchases/purchaseCreditNoteDuplicateSeed.ts", "PurchaseCreditNoteDetail"],
];

test("a document detail loader returns a detail only if it has its lines", () => {
  for (const [file, type] of DETAILS) {
    const src = read(file);
    assert.match(src, new RegExp(`objectWithLists<${type}>\\(\\s*r\\.data\\s*,\\s*"lines"\\s*\\)`), `${file} must narrow the ${type} it loads`);
    assert.ok(!new RegExp(`r\\.data as ${type}`).test(src), `${file} casts the payload to ${type} again`);
  }
});

test("a duplicate seed read back from the session is a detail only if it has its lines", () => {
  for (const [file, type] of SEEDS) {
    const src = read(file);
    assert.match(src, new RegExp(`objectWithLists<${type}>\\(\\s*JSON\\.parse\\(raw\\)\\s*,\\s*"lines"\\s*\\)`), `${file} must narrow the ${type} it reads back`);
    assert.ok(!new RegExp(`JSON\\.parse\\(raw\\) as ${type}`).test(src), `${file} casts the stored seed to ${type} again`);
  }
});

test("the editors that read existing.lines and duplicateSeed.lines are the ones whose sources are pinned above", () => {
  // If an editor starts taking its detail from somewhere else, the reads below are no longer covered by the two tests above.
  const editors = walk(join(WEB, "components")).map((f) => relative(WEB, f).split("\\").join("/")).filter((rel) =>
    /\bexisting && existing\.lines\.length\b/.test(read(rel)));
  assert.deepEqual(editors.sort(), [
    "components/invoices/InvoiceEditor.tsx",
    "components/purchases/DebitNoteEditor.tsx",
    "components/purchases/PurchaseBillEditor.tsx",
    "components/purchases/PurchaseCreditNoteEditor.tsx",
    "components/sales/SalesCreditNoteEditor.tsx",
    "components/sales/SalesDebitNoteEditor.tsx",
  ], "an editor was added or removed: add its loader and seed to DETAILS and SEEDS");
});

test("the TDS deduction preview and deposit state refuse an answer without the parts the screen reads", () => {
  const src = read("lib/data/tds.ts");
  assert.match(src, /objectOrNull\(shaped\.explain\)/, "previewTdsDeduction must refuse a preview without `explain`");
  assert.match(src, /objectWithLists<TdsDepositState>\(\s*resp\.data\s*,\s*"warnings"\s*\)/, "fetchTdsDepositState must need its warnings list");
  assert.match(src, /objectOrNull\(shaped\.deductions\)[\s\S]{0,40}objectOrNull\(shaped\.legend\)/, "and its two maps");
});

test("the capital-gains exemption working needs its three lists", () => {
  assert.match(read("lib/data/income-tax.ts"),
    /objectWithLists<CapitalGainExemption>\(\s*json\.data\s*,\s*"claims"\s*,\s*"gaps"\s*,\s*"caveats"\s*\)/);
});

test("a fixed-asset category with no classes keeps its place with an empty list, and a payload that is not a list is no categories", () => {
  const src = read("app/clients/[id]/fixed-assets/page.tsx");
  assert.match(src, /arrayOrEmpty<AssetCategory>\(\s*j\.data\s*\)/);
  assert.match(src, /classes:\s*arrayOrEmpty\(\s*c\.classes\s*\)/);
  const at = src.indexOf("/api/fixed-assets/categories");
  assert.ok(at > 0 && !/j\.data \?\? \[\]/.test(src.slice(at, at + 900)), "`j.data ?? []` passes a truthy non-list straight through");
});

test("the statement preview needs its balance check", () => {
  assert.match(read("components/banking/AccountsPanel.tsx"), /objectOrNull\(\s*shaped\.balance_check\s*\)/);
});

test("the walk still sees the reads this is about", () => {
  // The population of `x && x.a.b` reads of a nested field. Counted, so a regex that stopped matching fails here and not silently.
  let n = 0;
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f).split("\\").join("/");
    if (rel.startsWith("scripts/")) continue;
    n += [...read(rel).matchAll(/\b([A-Za-z_]\w*) && \1\.\w+\.\w+/g)].length;
  }
  assert.ok(n >= 20, `only ${n} root-guarded nested reads found: the walk has probably stopped matching`);
});
