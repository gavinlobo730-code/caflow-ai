// PR-2 sales-invoice import mapping tests. Run with:
//   node --experimental-strip-types --test lib/invoices/importMapping.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { buildSalesInvoices, type CustomerRef, type ServiceRef } from "./importMapping.ts";

const CUSTOMERS: CustomerRef[] = [
  { id: "cust-1", name: "Acme Pvt Ltd" },
  { id: "cust-2", name: "Beta LLP" },
];

const SERVICES: ServiceRef[] = [
  { id: "svc-1", name: "Statutory Audit", description: "Annual statutory audit", hsn_sac: "998221", gst_rate_bps: 1800, default_rate_paise: 5000000, unit: "OTH" },
  { id: "svc-2", name: "No Price Service", hsn_sac: "998222", gst_rate_bps: null, default_rate_paise: null, unit: null },
];

function row(o: Record<string, string>) { return o; }

test("rupees → integer paise and GST rate passed through as gst_rate_percent", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-0001", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Consulting", quantity: "1", rate: "1500.50", gst_rate: "18" })],
    "client-1", CUSTOMERS);
  assert.equal(errors.length, 0);
  assert.equal(invoices.length, 1);
  assert.equal(invoices[0].invoice_no, "INV-0001");
  assert.equal(invoices[0].lines[0].rate_paise, 150050);       // 1500.50 × 100
  assert.equal(invoices[0].lines[0].gst_rate_percent, 18);     // matches InvoiceLineIn.gst_rate_percent
  assert.equal(invoices[0].customer_id, "cust-1");
  assert.equal(invoices[0].client_id, "client-1");
});

test("rows sharing invoice_no group into one multi-line invoice", () => {
  const { invoices } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Line A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Line B", quantity: "2", rate: "200", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(invoices.length, 1);
  assert.equal(invoices[0].lines.length, 2);
});

test("different invoice_no → separate invoices even for the same customer/date", () => {
  const { invoices } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-2", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(invoices.length, 2);
});

test("missing invoice_no is reported and skipped", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "X", quantity: "1", rate: "100", gst_rate: "18" })],
    "client-1", CUSTOMERS);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /invoice_no is required/i);
});

test("unknown customer is reported and skipped", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Ghost Co", invoice_date: "2026-04-10", description: "X", quantity: "1", rate: "100", gst_rate: "18" })],
    "client-1", CUSTOMERS);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /unknown customer/i);
});

test("bad date and bad amount are reported", () => {
  const { errors } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "10-04-2026", description: "X", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-2", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Y", quantity: "0", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(errors.length, 2);
  assert.match(errors[0], /invoice_date/i);
  assert.match(errors[1], /quantity/i);
});

test("invoice_no reused across customers is rejected (group keeps its first customer)", () => {
  const { invoices, errors } = buildSalesInvoices([
    row({ invoice_no: "INV-9", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-9", customer: "Beta LLP", invoice_date: "2026-04-10", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.match(errors.join(" "), /different customer/i);
  assert.equal(invoices.length, 1);
  assert.equal(invoices[0].lines.length, 1); // only the first (consistent) row survives
});

test("invoice_no reused with a different invoice_date or due_date is rejected", () => {
  const { errors: dateErrors } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-11", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.match(dateErrors.join(" "), /different invoice_date/i);

  const { errors: dueDateErrors } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", due_date: "2026-05-10", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", due_date: "2026-06-10", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.match(dueDateErrors.join(" "), /different due_date/i);
});

test("invoice_no reused with a different supply_state_code is rejected", () => {
  const { errors } = buildSalesInvoices([
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", supply_state_code: "27", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", supply_state_code: "07", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.match(errors.join(" "), /different supply_state_code/i);
});

// ── Product/Service resolution ────────────────────────────────────────────
test("a known product_service pre-fills description/hsn/rate/gst/unit", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", product_service: "Statutory Audit", quantity: "1" })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(errors.length, 0);
  assert.equal(invoices[0].lines[0].description, "Annual statutory audit");
  assert.equal(invoices[0].lines[0].hsn_sac, "998221");
  assert.equal(invoices[0].lines[0].rate_paise, 5000000);
  assert.equal(invoices[0].lines[0].gst_rate_percent, 18);
  assert.equal(invoices[0].lines[0].unit, "OTH");
});

test("row's own fields override the matched product_service's defaults", () => {
  const { invoices } = buildSalesInvoices(
    [row({
      invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10",
      product_service: "Statutory Audit", description: "Custom description", rate: "60000", gst_rate: "12", quantity: "1",
    })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(invoices[0].lines[0].description, "Custom description");
  assert.equal(invoices[0].lines[0].rate_paise, 6000000);
  assert.equal(invoices[0].lines[0].gst_rate_percent, 12);
  // unit has no import column — it always comes from the matched
  // product_service (never row-level), so it's unaffected by other overrides.
  assert.equal(invoices[0].lines[0].unit, "OTH");
});

test("unknown product_service is reported and skipped", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", product_service: "Ghost Service", quantity: "1" })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /unknown product\/service/i);
});

test("a product_service with no default price still requires a rate", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", product_service: "No Price Service", description: "Line text", quantity: "1" })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /rate.*non-negative/i);
});

test("no product_service still requires description, rate and gst_rate directly", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", quantity: "1" })],
    "client-1", CUSTOMERS);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /description is required/i);
});

// A product_service with no description of its own never falls back to its
// Name — matches the manual editor's serviceToLine, which stopped doing this
// (a CA reported a blank-description preset silently filling the invoice
// line with the product name, which they never typed).
test("a product_service with no description of its own still requires a row-level description", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", product_service: "No Price Service", rate: "500", quantity: "1" })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /description is required/i);

  const ok = buildSalesInvoices(
    [row({ invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", product_service: "No Price Service", description: "Custom line text", rate: "500", gst_rate: "18", quantity: "1" })],
    "client-1", CUSTOMERS, SERVICES);
  assert.equal(ok.errors.length, 0);
  assert.equal(ok.invoices[0].lines[0].description, "Custom line text");
});
