// Bulk-import mapper tests. Run with:
//   node --experimental-strip-types --test lib/imports/imports.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildCustomers,
  buildVendors,
  buildPurchaseBills,
  buildReceipts,
  buildEmployees,
  type NameRef,
} from "./mappers.ts";

const row = (o: Record<string, string>) => o;

// ── Customers ────────────────────────────────────────────────────────────────
test("customers: rupees → paise, GSTIN derives state code, defaults credit_days", () => {
  const { records, errors } = buildCustomers([
    row({ name: "Acme Pvt Ltd", gstin: "27AABCU9603R1ZX", opening_balance: "1500.50" }),
  ], "client-1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].opening_balance_paise, 150050);
  assert.equal(records[0].state_code, "27");
  assert.equal(records[0].credit_days, 30);
  assert.equal(records[0].client_id, "client-1");
});

test("customers: invalid GSTIN and duplicate name reported", () => {
  const { records, errors } = buildCustomers([
    row({ name: "Bad Co", gstin: "NOTAGST" }),
    row({ name: "Dup" }),
    row({ name: "dup" }),
  ], "c1");
  assert.equal(records.length, 1); // only "Dup" survives
  assert.match(errors.join(" "), /invalid GSTIN/i);
  assert.match(errors.join(" "), /duplicate name/i);
});

// ── Vendors ──────────────────────────────────────────────────────────────────
test("vendors: TDS rate % → bps when applicable", () => {
  const { records, errors } = buildVendors([
    row({ name: "Supplier A", tds_applicable: "yes", tds_section: "194C", tds_rate: "2" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].tds_applicable, true);
  assert.equal(records[0].tds_rate_bps, 200);
  assert.equal(records[0].tds_section, "194C");
});

test("vendors: TDS applicable without valid section is rejected", () => {
  const { records, errors } = buildVendors([
    row({ name: "Supplier B", tds_applicable: "yes", tds_section: "999", tds_rate: "2" }),
  ], "c1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /tds_section/i);
});

// ── Purchase bills ─────────────────────────────────────────────────────────
const VENDORS: NameRef[] = [{ id: "v1", name: "Supplier A" }, { id: "v2", name: "Supplier B" }];

test("purchase bills: rows sharing bill_no group into one multi-line bill", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Supplier A", bill_no: "B-1", bill_date: "2026-04-10", description: "L1", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ vendor: "Supplier A", bill_no: "B-1", bill_date: "2026-04-10", description: "L2", quantity: "2", rate: "200.25", gst_rate: "18" }),
  ], "c1", VENDORS);
  assert.equal(errors.length, 0);
  assert.equal(bills.length, 1);
  assert.equal(bills[0].lines.length, 2);
  assert.equal(bills[0].vendor_id, "v1");
  assert.equal(bills[0].lines[1].rate_paise, 20025);
  assert.equal(bills[0].lines[1].gst_rate_percent, 18);
});

test("purchase bills: unknown vendor and bill_no reused across vendors reported", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Ghost", bill_date: "2026-04-10", description: "X", quantity: "1", rate: "10", gst_rate: "5" }),
    row({ vendor: "Supplier A", bill_no: "B-9", bill_date: "2026-04-10", description: "A", quantity: "1", rate: "10", gst_rate: "5" }),
    row({ vendor: "Supplier B", bill_no: "B-9", bill_date: "2026-04-10", description: "B", quantity: "1", rate: "10", gst_rate: "5" }),
  ], "c1", VENDORS);
  assert.match(errors.join(" "), /unknown vendor/i);
  assert.match(errors.join(" "), /different vendor/i);
  assert.equal(bills.length, 1); // only B-9 for Supplier A
});

// ── Receipts ─────────────────────────────────────────────────────────────────
const CUSTOMERS: NameRef[] = [{ id: "cu1", name: "Acme Pvt Ltd" }];

test("receipts: amount → paise, mode validated", () => {
  const { records, errors } = buildReceipts([
    row({ customer: "Acme Pvt Ltd", receipt_date: "2026-04-10", amount: "5000", payment_mode: "UPI", reference_no: "UTR1" }),
  ], "c1", CUSTOMERS);
  assert.equal(errors.length, 0);
  assert.equal(records[0].amount_paise, 500000);
  assert.equal(records[0].payment_mode, "upi");
});

test("receipts: bad mode and zero amount reported", () => {
  const { records, errors } = buildReceipts([
    row({ customer: "Acme Pvt Ltd", receipt_date: "2026-04-10", amount: "0", payment_mode: "bank" }),
    row({ customer: "Acme Pvt Ltd", receipt_date: "2026-04-10", amount: "100", payment_mode: "bitcoin" }),
  ], "c1", CUSTOMERS);
  assert.equal(records.length, 0);
  assert.match(errors[0], /amount/i);
  assert.match(errors[1], /payment_mode/i);
});

// ── Employees ────────────────────────────────────────────────────────────────
test("employees: basic → paise, boolean defaults", () => {
  const { records, errors } = buildEmployees([
    row({ name: "Ravi Kumar", basic: "25000" }),
  ], "c1", "firm-1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].basic_paise, 2500000);
  assert.equal(records[0].hra_percent, 40);
  assert.equal(records[0].pf_applicable, true);
  assert.equal(records[0].esi_applicable, true);
  assert.equal(records[0].pt_applicable, false);
  assert.equal(records[0].firm_id, "firm-1");
});

test("employees: full Aadhaar is reduced to last 4 only (never stored full)", () => {
  const { records, errors } = buildEmployees([
    row({ name: "Asha", basic: "30000", aadhaar: "1234 5678 9012" }),
  ], "c1", "f1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].aadhaar_last4, "9012");
  assert.ok(!("aadhaar" in records[0]));
});

test("employees: non-12-digit Aadhaar is rejected", () => {
  const { records, errors } = buildEmployees([
    row({ name: "Bad Aadhaar", basic: "30000", aadhaar: "12345" }),
  ], "c1", "f1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /aadhaar must be 12 digits/i);
});

test("employees: missing basic and invalid PAN reported", () => {
  const { records, errors } = buildEmployees([
    row({ name: "No Salary", basic: "" }),
    row({ name: "Bad Pan", basic: "10000", pan: "XXX" }),
  ], "c1", "f1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /basic/i);
  assert.match(errors[1], /PAN/i);
});
