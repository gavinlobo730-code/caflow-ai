// Sales Debit Note editor domain tests. Run with:
//   node --experimental-strip-types --test lib/sales/salesDebitNoteEditor.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { validateSalesDebitNoteEditor } from "./salesDebitNoteEditor.ts";
import { previewTotals } from "../invoices/gst.ts";
import type { InvoiceLine } from "../invoices/gst.ts";

function line(over: Partial<InvoiceLine> = {}): InvoiceLine {
  return {
    description: "Test line", hsn_sac: "998221", qty: "1", rate: "1000", gst_rate: 18,
    unit: "NOS", serviceCatalogueId: "SVC-1",
    ...over,
  };
}

test("validateSalesDebitNoteEditor requires customer, date and at least one valid line", () => {
  const v = validateSalesDebitNoteEditor({ customerId: "", debitNoteDate: "", lines: [] });
  assert.equal(v.ok, false);
  assert.ok(v.errors.customer);
  assert.ok(v.errors.debitNoteDate);
  assert.ok(v.errors.lines);
});

test("validateSalesDebitNoteEditor passes with customer, date and a valid line", () => {
  const v = validateSalesDebitNoteEditor({ customerId: "CUST-1", debitNoteDate: "2026-01-01", lines: [line()] });
  assert.equal(v.ok, true);
  assert.deepEqual(v.errors, {});
});

test("no reason field required — reason is optional on the backend, matching Purchase Debit Note parity", () => {
  const v = validateSalesDebitNoteEditor({ customerId: "CUST-1", debitNoteDate: "2026-01-01", lines: [line()] });
  assert.equal(v.ok, true);
});

test("sales debit note totals are NOT rupee-rounded (applyRoundOff=false), unlike a Sales Invoice", () => {
  const t = previewTotals([line({ qty: "1", rate: "105.55", gst_rate: 18 })], false, false);
  assert.equal(t.round_off_paise, 0);
  assert.equal(t.grand_total_paise, t.taxable_paise + t.gst_paise);
});
