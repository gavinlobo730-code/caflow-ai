// A read through the shared pager reads its error (POST-A-527). Run with:
//   node --experimental-strip-types --test scripts/a-pager-read-reads-its-error.test.ts
//
// WHY THIS EXISTS
//     `lib/supabase/selectAll.ts` exports two pagers, and both HAND A FAILURE BACK as `{ data, error }` and neither throws. A caller that took
//     `data` alone drew a refused read as an empty list, and a read that stopped partway as the whole list. Reading the 97 quiet catches
//     (POST-A-515 (d)) turned up four client pickers whose `catch` was written to cover exactly this and never ran, and twelve more reads
//     (sixteen sites in all) that had no catch at all:
//       * the receipt form's open invoices and the vendor payment form's open bills (a failed read said "This vendor has no open bills. The
//         whole payment is recorded as an advance.", which is a false statement on a screen that posts money);
//       * the bank settlement modal's customers, vendors and open documents (it posts to the ledger as well);
//       * the customer import's duplicate check (a failed read took every row for a new customer);
//       * the "Against invoice" and "Against bill" pickers of the sales credit and debit note editors and the purchase debit and credit note
//         editors (a standalone note is issued instead of one that names the invoice CGST §34 needs it to name);
//       * the fixed-asset form's vendor bills, the year-end adjustments' accounts, the bills-of-entry accounts, the recurring journal's
//         accounts and the knowledge base list.
//     Each says what could not be read now, in the screen's own words.
//
// THE RULE (scripts/pagerReads.ts holds it): the answer of an awaited `selectAll` or `selectAllKeyset` is taken as `{ data, error }` (or held
//     in a name whose `.error` is read), and the error is USED: named again in the same function. A pager call returned straight to the
//     caller hands the error on and is not judged.
//
// WHAT IT DOES NOT SEE: a helper that wraps the pager under another name, a result passed on before its `error` is read, and what a screen
//     does with the error once it is used. A reading that fails is not a reading, and what is drawn instead is the screen's to say.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { scanSource, scanTree } from "./pagerReads.ts";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const flagged = (src: string) => scanSource("app/x/page.tsx", src).findings.map((f) => `${f.fn}: ${f.why}`);

// ═══ THE TREE ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

test("every awaited pager read takes its error and looks at it", () => {
  const { findings } = scanTree(WEB);
  assert.deepEqual(
    findings.map((f) => `${f.file}:${f.line} ${f.fn}: ${f.why}`),
    [],
    "A read through the shared pager drops its error: the pager does not throw, so a refused or partial read is drawn as the whole list or as an empty one. Take `{ data, error }` and say what could not be read.",
  );
});

test("the scan reads the tree it claims to", () => {
  const { filesScanned, examined } = scanTree(WEB);
  assert.ok(filesScanned > 700, `only ${filesScanned} files were scanned: the walk lost a directory`);
  assert.ok(examined >= 40, `only ${examined} pager reads were examined: the scan stopped recognising them`);
});

// ═══ NEGATIVE CONTROLS ═════════════════════════════════════════════════════════════════════════════════════════════════════════════

test("it flags a pager read that takes data alone", () => {
  assert.deepEqual(flagged("async function a(){ const { data } = await selectAll(() => q()); return data; }"), ["a: the answer is taken as `{ data }` and its `error` is never read"]);
  assert.deepEqual(flagged("async function b(){ const { data: rows } = await selectAllKeyset(() => q()); return rows; }"), ["b: the answer is taken as `{ data }` and its `error` is never read"]);
});

test("it flags an error that is taken and never looked at", () => {
  assert.deepEqual(flagged("async function a(){ const { data, error } = await selectAll(() => q()); return data; }"), ["a: the `error` is taken as `error` and never looked at"]);
  assert.deepEqual(flagged("async function b(){ const { data, error: e } = await selectAll(() => q()); return data; }"), ["b: the `error` is taken as `e` and never looked at"]);
});

test("it flags an answer held whole whose error is never read, and an answer thrown away", () => {
  assert.deepEqual(flagged("async function a(){ const r = await selectAll(() => q()); return r.data; }"), ["a: the answer is held as `r` and `r.error` is never read"]);
  assert.deepEqual(flagged("async function b(){ await selectAll(() => q()); }"), ["b: the answer is thrown away"]);
});

test("it does not flag a read whose error is used", () => {
  assert.deepEqual(flagged("async function a(){ const { data, error } = await selectAll(() => q()); if (error) throw error; return data; }"), []);
  assert.deepEqual(flagged("async function b(){ const { data, error } = await selectAll(() => q()); setUnread(!!error); setRows(error ? [] : data ?? []); }"), []);
  assert.deepEqual(flagged("async function c(){ const { data, error: readError } = await selectAll(() => q()); if (readError) return null; return data; }"), []);
  assert.deepEqual(flagged("async function d(){ const r = await selectAll(() => q()); if (r.error) throw r.error; return r.data; }"), []);
  assert.deepEqual(flagged("async function e(){ return await selectAll(() => q()); }"), []);
  assert.deepEqual(flagged("function f(){ return selectAll(() => q()); }"), []);
});

test("a pager call that is not awaited is not this rule's", () => {
  assert.deepEqual(flagged("function a(){ return selectAll(() => q()).then((r) => r.data); }"), []);
});

// ═══ THE SIXTEEN SITES: each is pinned to the thing that was wrong ═════════════════════════════════════════════════════════════════

test("the receipt form and the vendor payment form say a failed read of the open documents", () => {
  const sales = read("app/clients/[id]/sales/page.tsx");
  assert.match(sales, /setOpenInvoicesUnread\(!!error\)/);
  assert.match(sales, /open invoices could not be read, so none can be allocated here/);
  const purchases = read("app/clients/[id]/purchases/page.tsx");
  assert.match(purchases, /setOpenBillsUnread\(!!error\)/);
  assert.ok(purchases.indexOf("openBillsUnread ? (") > 0 && purchases.indexOf("openBillsUnread ? (") < purchases.indexOf("This vendor has no open bills."),
    "the vendor payment form says the vendor has no open bills before it checks that the bills were read");
});

test("the customer import stops when it cannot read the customers already on file", () => {
  const src = read("app/clients/[id]/sales/page.tsx");
  const at = src.indexOf("const { records, errors } = buildCustomers(rows, clientId);");
  assert.ok(at > 0, "the customer import is no longer where this test looks");
  const body = src.slice(at, at + 3000);
  assert.match(body, /if \(existingError\) \{\s*return \{\s*imported: 0,/, "a failed snapshot no longer ends the import");
  assert.ok(body.indexOf("if (existingError)") < body.indexOf("/api/customers/bulk"), "the rows are sent before the snapshot is known to have been read");
});

test("the bank settlement modal says a failed read of the parties and of the open documents", () => {
  const src = read("components/banking/SettleDocumentsModal.tsx");
  assert.match(src, /setPartiesUnread\(!!error\)/);
  assert.match(src, /setDocsUnread\(!!error\)/);
  assert.ok(src.indexOf("docsUnread ? (") > 0 && src.indexOf("docsUnread ? (") < src.indexOf("No open {docLabel}s"));
});

test("the four note editors say a failed read of the invoices or bills a note may name", () => {
  for (const [rel, state] of [
    ["components/sales/SalesDebitNoteEditor.tsx", "openInvoicesUnread"],
    ["components/sales/SalesCreditNoteEditor.tsx", "openInvoicesUnread"],
    ["components/purchases/DebitNoteEditor.tsx", "openBillsUnread"],
    ["components/purchases/PurchaseCreditNoteEditor.tsx", "openBillsUnread"],
  ] as const) {
    const src = read(rel);
    assert.match(src, new RegExp(`set${state[0].toUpperCase()}${state.slice(1)}\\(!!error\\)`), `${rel} does not record a failed read`);
    assert.match(src, new RegExp(`\\{${state} && \\(`), `${rel} does not say it`);
  }
});

test("the other screens that read a list through the pager say a failed read", () => {
  assert.match(read("app/clients/[id]/fixed-assets/page.tsx"), /setVendorBillsUnread\(!!error\)/);
  assert.match(read("app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx"), /setAccountsUnread\(!!error\)/);
  assert.match(read("components/purchases/BillsOfEntryTab.tsx"), /setAccountsUnread\(!!error\)/);
  assert.match(read("app/accounting/recurring/page.tsx"), /setAccountsUnread\(!!error\)/);
  assert.match(read("app/clients/[id]/knowledge/page.tsx"), /if \(error\) throw new Error\("The articles could not be read\."\)/);
});
