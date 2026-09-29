// apex-sales-purchases-10: the Credit Notes and Debit Notes tabs on both the
// Sales and Purchases pages ran a full unpaged select-all over EVERY invoice
// (or bill) for the client inside the tab's `load()`, purely so `handleImport`
// could look up invoice/bill numbers referenced by an uploaded CSV — for a
// client with thousands of documents, opening a brand-new (zero-note) tab
// paged the whole invoice/bill table.
//
// THE FIX
//     load() no longer fetches client_sales_invoices / purchase_bills at all.
//     handleImport instead calls lookupOriginalInvoices / lookupOriginalBills,
//     which fetch ONLY the numbers referenced by the CSV, via a chunked
//     .in("invoice_no"/"bill_no", …) query, right before building the notes.
//
// Run with:
//   node --experimental-strip-types --test scripts/note-import-resolves-only-referenced-documents.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

const SALES_SRC = stripComments(read("app/clients/[id]/sales/page.tsx"));
const PURCHASES_SRC = stripComments(read("app/clients/[id]/purchases/page.tsx"));

test("lookupOriginalInvoices fetches ONLY the CSV's own invoice numbers, chunked", () => {
  const m = /async function lookupOriginalInvoices\([\s\S]*?\n\}/.exec(SALES_SRC);
  assert.ok(m, "lookupOriginalInvoices not found");
  const body = m[0];
  assert.match(body, /rows\.map\(\(r\) => \(r\.invoice_no \?\? ""\)\.trim\(\)\)\.filter\(Boolean\)/);
  assert.match(body, /\.in\("invoice_no", invoiceNos\.slice\(i, i \+ CHUNK\)\)/);
  assert.match(body, /\.from\("client_sales_invoices"\)/);
});

test("lookupOriginalBills fetches ONLY the CSV's own bill numbers, chunked", () => {
  const m = /async function lookupOriginalBills\([\s\S]*?\n\}/.exec(PURCHASES_SRC);
  assert.ok(m, "lookupOriginalBills not found");
  const body = m[0];
  assert.match(body, /rows\.map\(\(r\) => \(r\.bill_no \?\? ""\)\.trim\(\)\)\.filter\(Boolean\)/);
  assert.match(body, /\.in\("bill_no", billNos\.slice\(i, i \+ CHUNK\)\)/);
  assert.match(body, /\.from\("purchase_bills"\)/);
});

test("Sales Credit Notes and Sales Debit Notes tabs no longer eagerly load client_sales_invoices in their own load()", () => {
  // A tab-scoped `load` fetches credit_notes/sales_debit_notes; it must not
  // also carry a client_sales_invoices selectAll of its own any more — the
  // only remaining reference to that table on the page is inside
  // lookupOriginalInvoices (asserted above) and the Sales Invoices tab's OWN
  // load (a different function, FY-scoped, not the note tabs' concern here).
  const creditNotesLoad = /function CreditNotes\(\{[\s\S]*?const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[clientId, financialYear\]\);/.exec(SALES_SRC);
  assert.ok(creditNotesLoad, "CreditNotes load() not found");
  assert.doesNotMatch(creditNotesLoad[1], /\.from\("client_sales_invoices"\)/);

  const debitNotesLoad = /function SalesDebitNotes\(\{[\s\S]*?const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[clientId, financialYear\]\);/.exec(SALES_SRC);
  assert.ok(debitNotesLoad, "SalesDebitNotes load() not found");
  assert.doesNotMatch(debitNotesLoad[1], /\.from\("client_sales_invoices"\)/);
});

test("Purchase Debit Notes and Purchase Credit Notes tabs no longer eagerly load purchase_bills in their own load()", () => {
  const debitNotesLoad = /function DebitNotes\(\{[\s\S]*?const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[clientId, financialYear\]\);/.exec(PURCHASES_SRC);
  assert.ok(debitNotesLoad, "DebitNotes load() not found");
  assert.doesNotMatch(debitNotesLoad[1], /\.from\("purchase_bills"\)/);

  const creditNotesLoad = /function PurchaseCreditNotes\(\{[\s\S]*?const load = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[clientId, financialYear\]\);/.exec(PURCHASES_SRC);
  assert.ok(creditNotesLoad, "PurchaseCreditNotes load() not found");
  assert.doesNotMatch(creditNotesLoad[1], /\.from\("purchase_bills"\)/);
});

test("each handleImport calls the lookup right before building the notes", () => {
  assert.match(SALES_SRC, /const originalInvoices = await lookupOriginalInvoices\(clientId, rows\);\s*\n\s*const \{ notes, errors \} = buildSalesCreditNotes\(/);
  assert.match(SALES_SRC, /const originalInvoices = await lookupOriginalInvoices\(clientId, rows\);\s*\n\s*const \{ notes, errors \} = buildSalesDebitNotes\(/);
  assert.match(PURCHASES_SRC, /const originalBills = await lookupOriginalBills\(clientId, rows\);\s*\n\s*const \{ notes, errors \} = buildPurchaseDebitNotes\(/);
  assert.match(PURCHASES_SRC, /const originalBills = await lookupOriginalBills\(clientId, rows\);\s*\n\s*const \{ notes, errors \} = buildPurchaseCreditNotes\(/);
});
