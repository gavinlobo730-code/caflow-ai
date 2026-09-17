// ACC-22 — where a ledger row's document lives. Pure helpers, so they are
// tested here; the VOCABULARY is pinned from the Python side, in
// apps/api/tests/test_the_browser_can_open_the_document_the_ledger_names.py,
// because a guard written here would compare this file with itself.
//
// Run with:
//   node --experimental-strip-types --test lib/accounting/sourceDocument.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  documentTarget, noRouteReason, sourceLabel, journalEntryHref, documentHref, openedAt,
  ENTRY_IS_THE_RECORD, NO_ROUTE_REASON, ROUTED_SOURCES,
} from "./sourceDocument.ts";

const C = "CL-1";
const row = (source_type: string | null, source_id: string | null = "D-9") =>
  ({ entry_id: "E-1", source_type, source_id });

test("a document goes to its own screen, on its own tab", () => {
  assert.equal(documentTarget(C, row("sales_invoice"))!.href,
    "/clients/CL-1/sales?tab=invoices&doc=D-9");
  assert.equal(documentTarget(C, row("purchase_bill"))!.href,
    "/clients/CL-1/purchases?tab=bills&doc=D-9");
  assert.equal(documentTarget(C, row("bill_of_entry"))!.href,
    "/clients/CL-1/purchases?tab=bills-of-entry&doc=D-9");
  assert.equal(documentTarget(C, row("bank_transaction"))!.href,
    "/clients/CL-1/bank?tab=entries&doc=D-9");
});

test("the three sources that ARE the record go to the entry, not to a document", () => {
  // journal_source.ENTRY_IS_THE_RECORD. They carry no source_id at all, so a
  // target built from one would be a link to nothing.
  for (const st of ENTRY_IS_THE_RECORD) {
    const t = documentTarget(C, row(st, null));
    assert.equal(t!.href, "/clients/CL-1/accounting/journal/E-1/edit", st);
  }
});

test("a depreciation charge opens its ASSET", () => {
  // It has no document of its own; the asset is what explains it, which is
  // what journal_source says and what source_id actually holds.
  assert.equal(documentTarget(C, row("depreciation"))!.href,
    "/clients/CL-1/fixed-assets?tab=register&doc=D-9");
  assert.equal(documentTarget(C, row("asset_disposal"))!.href,
    "/clients/CL-1/fixed-assets?tab=register&doc=D-9");
});

test("no source, no link — and nothing to explain", () => {
  assert.equal(documentTarget(C, row(null, null)), null);
  assert.equal(noRouteReason(row(null, null)), "");
});

test("a source with a screen but no id does not offer a link", () => {
  // A source_type without its source_id is a breadcrumb leading nowhere.
  assert.equal(documentTarget(C, row("sales_invoice", null)), null);
  assert.match(noRouteReason(row("sales_invoice", null)), /records no document id/);
});

test("the two sources with nowhere to go say why", () => {
  for (const st of Object.keys(NO_ROUTE_REASON)) {
    assert.equal(documentTarget(C, row(st)), null, st);
    assert.ok(noRouteReason(row(st)).length > 40,
      `${st} must explain itself, not merely fail to open`);
  }
  // And the two reasons are DIFFERENT facts: one is about the employee, the
  // other about the engagement. A shared sentence would say the wrong thing
  // about one of them.
  const reasons = Object.values(NO_ROUTE_REASON);
  assert.equal(new Set(reasons).size, reasons.length);
});

test("an unknown source is named rather than routed", () => {
  assert.equal(documentTarget(C, row("something_new")), null);
  assert.match(noRouteReason(row("something_new")), /No screen in this product/);
});

test("the label is derived, so a source added tomorrow reads correctly", () => {
  assert.equal(sourceLabel("purchase_credit_note"), "Purchase credit note");
  assert.equal(sourceLabel("TrialBalance"), "Trial balance");
  assert.equal(sourceLabel(null), "—");
  assert.equal(sourceLabel("  "), "—");
});

test("ids are encoded into the href", () => {
  assert.equal(documentHref("c/1", "sales", "invoices", "a b&c"),
    "/clients/c/1/sales?tab=invoices&doc=a%20b%26c");
  assert.equal(journalEntryHref("CL-1", "E-2"), "/clients/CL-1/accounting/journal/E-2/edit");
});

test("openedAt reads the pair, and a blank value is absent", () => {
  assert.deepEqual(openedAt("?tab=bills&doc=D-9"), { tab: "bills", doc: "D-9" });
  assert.deepEqual(openedAt(""), { tab: null, doc: null });
  // ?doc= with nothing after it is a truncated link, not a document with an
  // empty id — treating it as one would ring no row and look like a bug.
  assert.deepEqual(openedAt("?tab=&doc="), { tab: null, doc: null });
  assert.deepEqual(openedAt("?cust=X"), { tab: null, doc: null });
});

test("no source is routed twice, and none is both routed and refused", () => {
  assert.equal(new Set(ROUTED_SOURCES).size, ROUTED_SOURCES.length);
  for (const st of ROUTED_SOURCES) {
    assert.ok(!NO_ROUTE_REASON[st], `${st} cannot both route and be refused`);
    assert.ok(!ENTRY_IS_THE_RECORD.includes(st),
      `${st} cannot be both a document and the entry itself`);
  }
});
