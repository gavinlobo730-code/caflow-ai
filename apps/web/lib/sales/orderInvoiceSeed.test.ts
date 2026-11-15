// POST-A-104 — an invoice raised from a sales order: the server's seed in the editor's shape, and the link kept only where it should be.
//   node --experimental-strip-types --test lib/sales/orderInvoiceSeed.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { invoiceDetailFromOrderSeed } from "./orderInvoiceSeed.ts";
import { seedForStorage } from "../invoices/duplicateSeed.ts";
import { toInvoiceLinePayload } from "../invoices/lineItemPayload.ts";

const answer = {
  order: { id: "O1", document_no: "SO/1" },
  seed: {
    customer_id: "X1", supply_state_code: "27", is_interstate: false,
    lines: [{
      description: "Widget", hsn_sac: "8471", quantity: "2.5", unit: "NOS", rate_paise: 5000, gst_rate_bps: 1800, is_service: false,
      service_catalogue_id: "S1", discount_percent_bps: null, cess_rate_bps: null, cess_specific_paise_per_unit: null,
      sales_order_line_id: "L1",
    }],
  },
  notes: [],
};

test("the seed is a new draft for the order's customer, each line naming the order line it bills", () => {
  const detail = invoiceDetailFromOrderSeed(answer);
  assert.ok(detail);
  assert.equal(detail.invoice_no, "");
  assert.equal(detail.status, "draft");
  assert.equal(detail.customer_id, "X1");
  assert.equal(detail.lines[0].quantity, 2.5);
  assert.equal(detail.lines[0].gst_rate_bps, 1800);
  assert.equal(detail.lines[0].sales_order_line_id, "L1");
});

test("a quantity the one parser cannot read is refused, never guessed", () => {
  const bad = { ...answer, seed: { ...answer.seed, lines: [{ ...answer.seed.lines[0], quantity: "two" }] } };
  assert.equal(invoiceDetailFromOrderSeed(bad), null);
});

test("an invoice raised from an order keeps its links; a duplicate of an invoice drops them", () => {
  const detail = invoiceDetailFromOrderSeed(answer);
  assert.ok(detail);
  assert.equal(seedForStorage(detail, true).lines[0].sales_order_line_id, "L1");
  assert.equal(seedForStorage(detail, false).lines[0].sales_order_line_id, null);
  assert.equal(detail.lines[0].sales_order_line_id, "L1", "stripping makes a copy and leaves the source alone");
});

test("the payload sends the link where a line has one and leaves the key out where it does not", () => {
  const base = { description: "Widget", hsn_sac: "8471", qty: "1", rate: "50", gst_rate: 18, serviceCatalogueId: "S1" };
  assert.equal(toInvoiceLinePayload({ ...base, salesOrderLineId: "L1" }).sales_order_line_id, "L1");
  assert.ok(!("sales_order_line_id" in toInvoiceLinePayload(base)));
  assert.ok(!("sales_order_line_id" in toInvoiceLinePayload({ ...base, salesOrderLineId: null })));
});
