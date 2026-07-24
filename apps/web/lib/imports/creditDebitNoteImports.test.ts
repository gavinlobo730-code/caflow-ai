// Credit/Debit Note bulk-import mapper tests. Run with:
//   node --experimental-strip-types --test lib/imports/creditDebitNoteImports.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSalesCreditNotes,
  buildSalesDebitNotes,
  buildPurchaseDebitNotes,
  buildPurchaseCreditNotes,
  type NameRef,
  type OriginalDocRef,
  type SalesServiceRef,
  type PurchaseServiceRef,
} from "./mappers.ts";

const row = (o: Record<string, string>) => o;

const customers: NameRef[] = [{ id: "cust-1", name: "Acme Pvt Ltd" }, { id: "cust-2", name: "Beta Co" }];
const vendors: NameRef[] = [{ id: "vend-1", name: "Steel Supplies" }];

const invoices: OriginalDocRef[] = [
  { id: "inv-1", no: "INV-001", partyId: "cust-1", isInterstate: true },
];
const bills: OriginalDocRef[] = [
  { id: "bill-1", no: "BILL-001", partyId: "vend-1", isInterstate: false },
];

const salesServices: SalesServiceRef[] = [
  { id: "svc-1", name: "Widget", description: "A widget", hsn_sac: "8501", gst_rate_bps: 1800, default_rate_paise: 100000, unit: "NOS" },
];
const purchaseServices: PurchaseServiceRef[] = [
  { id: "psvc-1", name: "Steel Rod", description: "TMT steel rod", hsn_sac: "7213", gst_rate_bps: 1800, purchase_price_paise: 50000, unit: "KGS" },
];

// ── Sales Credit Notes ───────────────────────────────────────────────────────

test("sales credit notes: linking invoice_no derives customer_id and is_interstate, ignoring a conflicting explicit column", () => {
  const { notes, errors } = buildSalesCreditNotes([
    row({ customer: "Acme Pvt Ltd", invoice_no: "INV-001", credit_note_date: "2026-04-10",
      is_interstate: "no", product_service: "Widget", quantity: "2" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(errors.length, 0);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].customer_id, "cust-1");
  assert.equal(notes[0].sales_invoice_id, "inv-1");
  assert.equal(notes[0].is_interstate, true); // derived from the linked invoice, not the "no" column
  assert.equal(notes[0].lines[0].service_catalogue_id, "svc-1");
  assert.equal(notes[0].lines[0].rate_paise, 100000); // pre-filled from the catalogue default
});

test("sales credit notes: standalone note (no invoice_no) uses the explicit is_interstate column", () => {
  const { notes, errors } = buildSalesCreditNotes([
    row({ customer: "Beta Co", credit_note_date: "2026-04-11", is_interstate: "yes",
      product_service: "Widget", quantity: "1", rate: "500", gst_rate: "18" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(errors.length, 0);
  assert.equal(notes[0].customer_id, "cust-2");
  assert.equal(notes[0].sales_invoice_id, undefined);
  assert.equal(notes[0].is_interstate, true);
});

test("sales credit notes: missing product_service is rejected (mandatory on every line)", () => {
  const { notes, errors } = buildSalesCreditNotes([
    row({ customer: "Acme Pvt Ltd", credit_note_date: "2026-04-10", description: "Manual line", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(notes.length, 0);
  assert.match(errors.join(" "), /product_service is required/i);
});

test("sales credit notes: customer mismatched against the linked invoice's own customer is rejected", () => {
  const { notes, errors } = buildSalesCreditNotes([
    row({ customer: "Beta Co", invoice_no: "INV-001", credit_note_date: "2026-04-10", product_service: "Widget", quantity: "1" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(notes.length, 0);
  assert.match(errors.join(" "), /does not match the customer/i);
});

test("sales credit notes: note_ref groups multiple lines into one note", () => {
  const { notes, errors } = buildSalesCreditNotes([
    row({ customer: "Beta Co", credit_note_date: "2026-04-11", note_ref: "CN-A", product_service: "Widget", quantity: "1", rate: "500", gst_rate: "18" }),
    row({ customer: "Beta Co", credit_note_date: "2026-04-11", note_ref: "CN-A", product_service: "Widget", quantity: "2", rate: "500", gst_rate: "18" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(errors.length, 0);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].lines.length, 2);
});

// ── Sales Debit Notes ────────────────────────────────────────────────────────

test("sales debit notes: linking invoice_no derives is_interstate from the invoice", () => {
  const { notes, errors } = buildSalesDebitNotes([
    row({ customer: "Acme Pvt Ltd", invoice_no: "INV-001", debit_note_date: "2026-04-12", product_service: "Widget", quantity: "1" }),
  ], "client-1", customers, invoices, salesServices);
  assert.equal(errors.length, 0);
  assert.equal(notes[0].is_interstate, true);
  assert.equal(notes[0].sales_invoice_id, "inv-1");
});

// ── Purchase Debit Notes ─────────────────────────────────────────────────────

test("purchase debit notes: linking bill_no derives vendor_id and is_interstate; reverse charge column parsed", () => {
  const { notes, errors } = buildPurchaseDebitNotes([
    row({ vendor: "Steel Supplies", bill_no: "BILL-001", debit_note_date: "2026-04-13",
      is_reverse_charge: "yes", product_service: "Steel Rod", quantity: "10" }),
  ], "client-1", vendors, bills, purchaseServices);
  assert.equal(errors.length, 0);
  assert.equal(notes[0].vendor_id, "vend-1");
  assert.equal(notes[0].purchase_bill_id, "bill-1");
  assert.equal(notes[0].is_interstate, false);
  assert.equal(notes[0].is_reverse_charge, true);
  assert.equal(notes[0].lines[0].rate_paise, 50000);
});

test("purchase debit notes: unknown bill_no is rejected", () => {
  const { notes, errors } = buildPurchaseDebitNotes([
    row({ vendor: "Steel Supplies", bill_no: "BILL-999", debit_note_date: "2026-04-13", product_service: "Steel Rod", quantity: "1" }),
  ], "client-1", vendors, bills, purchaseServices);
  assert.equal(notes.length, 0);
  assert.match(errors.join(" "), /unknown bill_no/i);
});

// ── Purchase Credit Notes ────────────────────────────────────────────────────

test("purchase credit notes: standalone note uses explicit is_interstate; bill_no groups lines", () => {
  const { notes, errors } = buildPurchaseCreditNotes([
    row({ vendor: "Steel Supplies", credit_note_date: "2026-04-14", is_interstate: "yes", product_service: "Steel Rod", quantity: "5" }),
  ], "client-1", vendors, bills, purchaseServices);
  assert.equal(errors.length, 0);
  assert.equal(notes[0].is_interstate, true);
  assert.equal(notes[0].purchase_bill_id, undefined);
});
