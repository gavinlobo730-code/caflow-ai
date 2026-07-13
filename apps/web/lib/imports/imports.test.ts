// Bulk-import mapper tests. Run with:
//   node --experimental-strip-types --test lib/imports/imports.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildCustomers,
  buildVendors,
  buildServices,
  buildPurchaseBills,
  buildReceipts,
  buildEmployees,
  type NameRef,
  type PurchaseServiceRef,
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

test("customers: blank/absent opening_balance maps to 0, never NaN", () => {
  // toPaise("") is NaN, and JSON.stringify(NaN) becomes `null` on the wire —
  // the backend's opening_balance_paise: int = 0 (non-Optional) rejects a
  // literal null, so every row leaving this optional column blank used to
  // fail bulk import outright.
  const { records, errors } = buildCustomers([
    row({ name: "No Opening Balance Field" }),           // column absent entirely
    row({ name: "Blank Opening Balance", opening_balance: "" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].opening_balance_paise, 0);
  assert.equal(Number.isNaN(records[0].opening_balance_paise), false);
  assert.equal(records[1].opening_balance_paise, 0);
});

test("customers: garbage opening_balance is a clear per-row error, not a silent NaN", () => {
  const { records, errors } = buildCustomers([
    row({ name: "Garbage Balance", opening_balance: "not-a-number" }),
  ], "c1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /opening_balance must be a valid number/i);
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

test("vendors: blank/absent opening_balance maps to 0, never NaN", () => {
  const { records, errors } = buildVendors([
    row({ name: "No Opening Balance Field" }),           // column absent entirely
    row({ name: "Blank Opening Balance", opening_balance: "" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].opening_balance_paise, 0);
  assert.equal(Number.isNaN(records[0].opening_balance_paise), false);
  assert.equal(records[1].opening_balance_paise, 0);
});

test("vendors: garbage opening_balance is a clear per-row error, not a silent NaN", () => {
  const { records, errors } = buildVendors([
    row({ name: "Garbage Balance", opening_balance: "not-a-number" }),
  ], "c1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /opening_balance must be a valid number/i);
});

test("vendors: credit_days defaults to 30 when blank, honours an explicit value", () => {
  const { records, errors } = buildVendors([
    row({ name: "No Credit Days Field" }),
    row({ name: "Explicit Credit Days", credit_days: "45" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].credit_days, 30);
  assert.equal(records[1].credit_days, 45);
});

test("vendors: negative credit_days is a clear per-row error", () => {
  const { records, errors } = buildVendors([
    row({ name: "Negative Credit Days", credit_days: "-5" }),
  ], "c1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /credit_days must be a non-negative whole number/i);
});

// ── Products & Services ──────────────────────────────────────────────────────
test("services: only name required, rest defaults sensibly", () => {
  const { records, errors } = buildServices([row({ name: "Bare Minimum" })], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].name, "Bare Minimum");
  assert.equal(records[0].kind, "service");
  assert.equal(records[0].gst_rate_bps, 1800); // defaults to 18%
  assert.equal(records[0].default_rate_paise, 0);
  assert.equal(records[0].purchase_price_paise, undefined);
  assert.equal(records[0].hsn_sac, undefined);
  assert.equal(records[0].client_id, "c1");
  // Unit/opening stock are goods-only (CGST Rule 46(h): UQC applies to
  // goods, not services) — a service row never gets a value for either,
  // even if the CSV happened to have data in those columns.
  assert.equal(records[0].unit, undefined);
  assert.equal(records[0].opening_qty_units, undefined);
  assert.equal(records[0].opening_cost_paise, undefined);
});

test("services: rupees → paise, percent → bps, kind validated", () => {
  const { records, errors } = buildServices([
    row({ name: "Steel Rod", kind: "good", gst_rate: "18", selling_price: "1500.50", purchase_price: "1000" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].kind, "good");
  assert.equal(records[0].gst_rate_bps, 1800);
  assert.equal(records[0].default_rate_paise, 150050);
  assert.equal(records[0].purchase_price_paise, 100000);
});

test("services: \"product\" is accepted as an alias for the internal \"good\" value", () => {
  // The app shows "Product" everywhere (the Kind dropdown, the catalogue
  // list) — a CA typing what they see in the app must not be rejected, even
  // though "good" stays the internal/API value.
  const { records, errors } = buildServices([row({ name: "Steel Rod", kind: "Product" })], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].kind, "good");
});

test("services: invalid kind and duplicate name reported", () => {
  const { records, errors } = buildServices([
    row({ name: "Bad Kind", kind: "widget" }),
    row({ name: "Dup" }),
    row({ name: "dup" }),
  ], "c1");
  assert.equal(records.length, 1); // only "Dup" survives
  assert.match(errors.join(" "), /kind must be/i);
  assert.match(errors.join(" "), /duplicate name/i);
});

test("services: blank name is rejected", () => {
  const { records, errors } = buildServices([row({ name: "  " })], "c1");
  assert.equal(records.length, 0);
  assert.match(errors[0], /name is required/i);
});

test("services: unit and opening stock import for a goods row", () => {
  const { records, errors } = buildServices([
    row({ name: "Bottled Water", kind: "good", unit: "kgs", opening_qty: "100", opening_cost: "5000" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].unit, "KGS");
  assert.equal(records[0].opening_qty_units, 100);
  assert.equal(records[0].opening_cost_paise, 500000);
});

test("services: unit and opening stock are dropped for a service row even if present in the CSV", () => {
  const { records, errors } = buildServices([
    row({ name: "Consulting", kind: "service", unit: "hrs", opening_qty: "10", opening_cost: "500" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].unit, undefined);
  assert.equal(records[0].opening_qty_units, undefined);
  assert.equal(records[0].opening_cost_paise, undefined);
});

test("services: opening qty of exactly 0 is treated as unset, not a seed signal", () => {
  const { records, errors } = buildServices([
    row({ name: "Bottled Water", kind: "good", opening_qty: "0", opening_cost: "0" }),
  ], "c1");
  assert.equal(errors.length, 0);
  assert.equal(records[0].opening_qty_units, undefined);
  assert.equal(records[0].opening_cost_paise, 0);
});

test("services: negative opening qty/cost rejected", () => {
  const badQty = buildServices([row({ name: "A", kind: "good", opening_qty: "-1" })], "c1");
  assert.equal(badQty.records.length, 0);
  assert.match(badQty.errors[0], /opening qty/i);

  const badCost = buildServices([row({ name: "B", kind: "good", opening_cost: "-1" })], "c1");
  assert.equal(badCost.records.length, 0);
  assert.match(badCost.errors[0], /opening stock value/i);
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

const PURCHASE_SERVICES: PurchaseServiceRef[] = [
  { id: "s1", name: "TMT Steel Rod 12mm", description: "Steel bar", hsn_sac: "7214", gst_rate_bps: 1800, purchase_price_paise: 5800, unit: "KGS" },
];

test("purchase bills: product_service links the line (service_catalogue_id) so a received bill can restock inventory", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Supplier A", bill_date: "2026-04-10", product_service: "TMT Steel Rod 12mm", quantity: "100" }),
  ], "c1", VENDORS, PURCHASE_SERVICES);
  assert.equal(errors.length, 0);
  assert.equal(bills[0].lines[0].service_catalogue_id, "s1");
  // Pre-filled from the matched product since the row gave none of its own.
  assert.equal(bills[0].lines[0].description, "Steel bar");
  assert.equal(bills[0].lines[0].hsn_sac, "7214");
  assert.equal(bills[0].lines[0].rate_paise, 5800);
  assert.equal(bills[0].lines[0].gst_rate_percent, 18);
  assert.equal(bills[0].lines[0].unit, "KGS");
});

test("purchase bills: row-level description/hsn_sac/rate/gst_rate override the matched product's own values", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Supplier A", bill_date: "2026-04-10", product_service: "TMT Steel Rod 12mm",
          description: "Bulk order", hsn_sac: "7215", quantity: "50", rate: "60", gst_rate: "12" }),
  ], "c1", VENDORS, PURCHASE_SERVICES);
  assert.equal(errors.length, 0);
  assert.equal(bills[0].lines[0].service_catalogue_id, "s1"); // still linked
  assert.equal(bills[0].lines[0].description, "Bulk order");
  assert.equal(bills[0].lines[0].hsn_sac, "7215");
  assert.equal(bills[0].lines[0].rate_paise, 6000);
  assert.equal(bills[0].lines[0].gst_rate_percent, 12);
});

test("purchase bills: unknown product_service is reported, not silently ignored", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Supplier A", bill_date: "2026-04-10", product_service: "Nonexistent Widget", quantity: "1" }),
  ], "c1", VENDORS, PURCHASE_SERVICES);
  assert.equal(bills.length, 0);
  assert.match(errors.join(" "), /unknown product\/service/i);
});

test("purchase bills: no product_service still requires description/rate/gst_rate (unlinked, free-text line)", () => {
  const { bills, errors } = buildPurchaseBills([
    row({ vendor: "Supplier A", bill_date: "2026-04-10", quantity: "1" }),
  ], "c1", VENDORS, PURCHASE_SERVICES);
  assert.equal(bills.length, 0);
  assert.match(errors.join(" "), /description is required/i);
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
