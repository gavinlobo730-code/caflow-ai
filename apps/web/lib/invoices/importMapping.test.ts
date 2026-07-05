// PR-2 sales-invoice import mapping tests. Run with:
//   node --experimental-strip-types --test lib/invoices/importMapping.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { buildSalesInvoices, type CustomerRef } from "./importMapping.ts";

const CUSTOMERS: CustomerRef[] = [
  { id: "cust-1", name: "Acme Pvt Ltd" },
  { id: "cust-2", name: "Beta LLP" },
];

function row(o: Record<string, string>) { return o; }

test("rupees → integer paise and GST rate passed through as gst_rate_percent", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Consulting", quantity: "1", rate: "1500.50", gst_rate: "18" })],
    "client-1", CUSTOMERS);
  assert.equal(errors.length, 0);
  assert.equal(invoices.length, 1);
  assert.equal(invoices[0].lines[0].rate_paise, 150050);       // 1500.50 × 100
  assert.equal(invoices[0].lines[0].gst_rate_percent, 18);     // matches InvoiceLineIn.gst_rate_percent
  assert.equal(invoices[0].customer_id, "cust-1");
  assert.equal(invoices[0].client_id, "client-1");
});

test("rows sharing invoice_ref group into one multi-line invoice", () => {
  const { invoices } = buildSalesInvoices([
    row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", invoice_ref: "INV-1", description: "Line A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", invoice_ref: "INV-1", description: "Line B", quantity: "2", rate: "200", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(invoices.length, 1);
  assert.equal(invoices[0].lines.length, 2);
});

test("different customers without ref → separate invoices", () => {
  const { invoices } = buildSalesInvoices([
    row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ customer: "Beta LLP", invoice_date: "2026-04-10", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(invoices.length, 2);
});

test("unknown customer is reported and skipped", () => {
  const { invoices, errors } = buildSalesInvoices(
    [row({ customer: "Ghost Co", invoice_date: "2026-04-10", description: "X", quantity: "1", rate: "100", gst_rate: "18" })],
    "client-1", CUSTOMERS);
  assert.equal(invoices.length, 0);
  assert.match(errors[0], /unknown customer/i);
});

test("bad date and bad amount are reported", () => {
  const { errors } = buildSalesInvoices([
    row({ customer: "Acme Pvt Ltd", invoice_date: "10-04-2026", description: "X", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "Y", quantity: "0", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.equal(errors.length, 2);
  assert.match(errors[0], /invoice_date/i);
  assert.match(errors[1], /quantity/i);
});

test("ref reused across customers is rejected", () => {
  const { errors } = buildSalesInvoices([
    row({ customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", invoice_ref: "INV-9", description: "A", quantity: "1", rate: "100", gst_rate: "18" }),
    row({ customer: "Beta LLP", invoice_date: "2026-04-10", invoice_ref: "INV-9", description: "B", quantity: "1", rate: "100", gst_rate: "18" }),
  ], "client-1", CUSTOMERS);
  assert.match(errors.join(" "), /different customer/i);
});
