// Credit/Debit Note bulk-import mapper tests. Run with:
//   node --experimental-strip-types --test lib/imports/creditDebitNoteImports.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  SALES_CREDIT_NOTE_IMPORT_COLUMNS,
  SALES_DEBIT_NOTE_IMPORT_COLUMNS,
  PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS,
  PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS,
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

// ── "Did the goods come back?" (POST-A-378) ─────────────────────────────────

const creditRow = (extra: Record<string, string>) => row({ customer: "Acme Pvt Ltd", invoice_no: "INV-001", credit_note_date: "2026-04-10", product_service: "Widget", quantity: "1", ...extra });
const debitRow = (extra: Record<string, string>) => row({ vendor: "Steel Supplies", bill_no: "BILL-001", debit_note_date: "2026-04-13", product_service: "Steel Rod", quantity: "1", ...extra });

test("goods returned: only the two imports whose notes can move stock offer the column", () => {
  const keys = (cols: { key: string }[]) => cols.map((c) => c.key);
  assert.ok(keys(SALES_CREDIT_NOTE_IMPORT_COLUMNS).includes("goods_returned"));
  assert.ok(keys(PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS).includes("goods_returned"));
  assert.ok(!keys(SALES_DEBIT_NOTE_IMPORT_COLUMNS).includes("goods_returned"), "a sales debit note moves no stock");
  assert.ok(!keys(PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS).includes("goods_returned"), "a purchase credit note moves no stock");
});

test("goods returned: a stated answer reaches the note as sent, and a note whose file did not say carries no key at all", () => {
  for (const [word, expected] of [["yes", true], ["Y", true], ["true", true], ["1", true], ["no", false], ["N", false], ["false", false], ["0", false]] as const) {
    const { notes, errors } = buildSalesCreditNotes([creditRow({ goods_returned: word })], "client-1", customers, invoices, salesServices);
    assert.deepEqual(errors, [], word);
    assert.equal(notes[0].goods_returned, expected, `credit note: ${word}`);
    const dn = buildPurchaseDebitNotes([debitRow({ goods_returned: word })], "client-1", vendors, bills, purchaseServices);
    assert.deepEqual(dn.errors, [], word);
    assert.equal(dn.notes[0].goods_returned, expected, `debit note: ${word}`);
  }
  for (const blank of [{}, { goods_returned: "" }, { goods_returned: "   " }] as Record<string, string>[]) {
    const { notes } = buildSalesCreditNotes([creditRow(blank)], "client-1", customers, invoices, salesServices);
    assert.equal("goods_returned" in notes[0], false, "an unstated answer is not sent: the server reads the key's absence as 'not stated'");
    const dn = buildPurchaseDebitNotes([debitRow(blank)], "client-1", vendors, bills, purchaseServices);
    assert.equal("goods_returned" in dn.notes[0], false);
  }
});

test("goods returned: a word that is neither yes nor no is refused and never read as no (no would tell the server to leave stock alone)", () => {
  for (const word of ["maybe", "returned", "nope", "2", "yes please"]) {
    const { notes, errors } = buildSalesCreditNotes([creditRow({ goods_returned: word })], "client-1", customers, invoices, salesServices);
    assert.equal(notes.length, 0, word);
    assert.match(errors.join(" "), /goods_returned must be yes or no/, word);
    const dn = buildPurchaseDebitNotes([debitRow({ goods_returned: word })], "client-1", vendors, bills, purchaseServices);
    assert.equal(dn.notes.length, 0, word);
    assert.match(dn.errors.join(" "), /goods_returned must be yes or no/, word);
  }
});

test("goods returned: the rows of one note must agree, and one stated row is enough for the note", () => {
  const same = buildSalesCreditNotes([creditRow({ goods_returned: "yes" }), creditRow({ goods_returned: "" })], "client-1", customers, invoices, salesServices);
  assert.deepEqual(same.errors, []);
  assert.equal(same.notes.length, 1);
  assert.equal(same.notes[0].goods_returned, true);
  assert.equal(same.notes[0].lines.length, 2);
  const late = buildSalesCreditNotes([creditRow({ goods_returned: "" }), creditRow({ goods_returned: "no" })], "client-1", customers, invoices, salesServices);
  assert.equal(late.notes[0].goods_returned, false);
  const clash = buildSalesCreditNotes([creditRow({ goods_returned: "yes" }), creditRow({ goods_returned: "no" })], "client-1", customers, invoices, salesServices);
  assert.match(clash.errors.join(" "), /disagree on goods_returned/);
  assert.equal(clash.notes[0].lines.length, 1, "the row that disagrees is left out, as any refused row is");
  const clashDn = buildPurchaseDebitNotes([debitRow({ goods_returned: "no" }), debitRow({ goods_returned: "yes" })], "client-1", vendors, bills, purchaseServices);
  assert.match(clashDn.errors.join(" "), /disagree on goods_returned/);
});

test("goods returned: the other two imports do not read the cell at all, so a file that happens to carry the column is not refused by it", () => {
  for (const word of ["no", "maybe", "t"]) {
    const sdn = buildSalesDebitNotes([row({ customer: "Acme Pvt Ltd", invoice_no: "INV-001", debit_note_date: "2026-04-12", product_service: "Widget", quantity: "1", goods_returned: word })], "client-1", customers, invoices, salesServices);
    assert.deepEqual(sdn.errors, [], word);
    assert.equal("goods_returned" in sdn.notes[0], false, word);
    const pcn = buildPurchaseCreditNotes([row({ vendor: "Steel Supplies", bill_no: "BILL-001", credit_note_date: "2026-04-14", product_service: "Steel Rod", quantity: "1", goods_returned: word })], "client-1", vendors, bills, purchaseServices);
    assert.deepEqual(pcn.errors, [], word);
    assert.equal("goods_returned" in pcn.notes[0], false, word);
  }
});

test("goods returned: the column's hint says what happened to the goods in the words of the note's own kind, and says two notes on one document need a Note Reference", () => {
  const hint = (cols: { key: string; hint?: string }[]) => cols.find((c) => c.key === "goods_returned")?.hint ?? "";
  assert.match(hint(SALES_CREDIT_NOTE_IMPORT_COLUMNS), /physically come back\?/);
  assert.match(hint(PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS), /physically go back to the supplier\?/);
  assert.doesNotMatch(hint(PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS), /come back/);
  for (const cols of [SALES_CREDIT_NOTE_IMPORT_COLUMNS, PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS]) assert.match(hint(cols), /Note Reference/);
});

test("goods returned: two notes against one document that disagree are refused in a sentence that says how to separate them", () => {
  const clash = buildSalesCreditNotes([creditRow({ goods_returned: "yes" }), creditRow({ goods_returned: "no" })], "client-1", customers, invoices, salesServices);
  assert.match(clash.errors.join(" "), /disagree on goods_returned \(if they are two separate notes, give each its own Note Reference\)/);
  const separate = buildSalesCreditNotes([creditRow({ goods_returned: "yes", note_ref: "N1" }), creditRow({ goods_returned: "no", note_ref: "N2" })], "client-1", customers, invoices, salesServices);
  assert.deepEqual(separate.errors, []);
  assert.deepEqual(separate.notes.map((n) => n.goods_returned), [true, false]);
});
