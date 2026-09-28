// A document's journal drill-through reads the real entry, not a mock-backed
// list search (apex-sales-purchases-01). Run with:
//   node --experimental-strip-types --test scripts/a-document-drawers-journal-drill-through-reads-the-real-entry.test.ts
//
// WHAT WAS WRONG
//     Six document-view drawers opened their "View Journal" drill-through by
//     calling GET /api/accounting/journal with the document's own date as a
//     start/end window, then searching the result for a row matching
//     journal_entry_id. That route answered from
//     `accounting_service.list_journal_entries`, an in-memory
//     MOCK_JOURNAL_ENTRIES filter that never reads the real database in any
//     deployment — so the search always came back empty and every drawer
//     rendered "line detail unavailable here." for a posting that
//     GET /api/accounting/journal/{id} (the real, DB-backed, single-entry
//     endpoint) had all along. Reproduced live on invoice INV-BULK-02999 and
//     purchase bill UFLPAC-26-27-0006.
//
// THE RULE
//     Each drawer already knows its own document's journal_entry_id — there
//     is nothing to search for. A drawer's drill-through must call the by-id
//     endpoint directly and must never rebuild the retired date-windowed
//     list call. `apps/api/tests/test_a_documents_journal_drill_through_
//     reads_the_real_entry.py` pins the backend half (the embed that lets the
//     by-id response name each line's account, and that the list route is
//     gone); this pins that the six screens actually call the fixed endpoint.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");

const DRAWERS = [
  "components/invoices/InvoiceViewDrawer.tsx",
  "components/purchases/PurchaseBillViewDrawer.tsx",
  "components/purchases/DebitNoteViewDrawer.tsx",
  "components/purchases/PurchaseCreditNoteViewDrawer.tsx",
  "components/sales/SalesCreditNoteViewDrawer.tsx",
  "components/sales/SalesDebitNoteViewDrawer.tsx",
];

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("none of the six drawers rebuild the retired date-windowed journal LIST call", () => {
  for (const rel of DRAWERS) {
    const src = code(rel);
    assert.doesNotMatch(
      src, /\/api\/accounting\/journal\?client_id=.*start_date=/,
      `${rel} still searches the mock-backed GET /api/accounting/journal list ` +
      "route by date window — that route only ever reads MOCK_JOURNAL_ENTRIES");
    assert.doesNotMatch(
      src, /entries\.find\(\(e\)\s*=>\s*e\.id ===/,
      `${rel} still searches a list result for its own journal_entry_id`);
  }
});

test("every drawer's drill-through reads the document's own journal_entry_id by id", () => {
  for (const rel of DRAWERS) {
    const src = code(rel);
    assert.match(
      src, /`\/api\/accounting\/journal\/\$\{[^}]*journal_entry_id\}`/,
      `${rel} must call GET /api/accounting/journal/{journal_entry_id} directly`);
  }
});

test("the dead client-side LIST helper is gone, and the by-id one is not", () => {
  const src = code("lib/api/index.ts");
  assert.doesNotMatch(
    src, /journal:\s*\(params\?/,
    "api.accounting.journal(params) — the date-windowed list helper — had no " +
    "caller left once the six drawers moved to the by-id endpoint");
  assert.match(
    src, /getJournalEntry:\s*\(id: string\)/,
    "the real, DB-backed single-entry helper must still be here");
  // The CREATE route shares the same URL as the retired LIST one (POST vs
  // GET) and must not be mistaken for it or deleted alongside it.
  assert.match(
    src, /createJournalEntry:\s*\(data: unknown\)/,
    "POST /api/accounting/journal (create) is a different, live endpoint");
});
