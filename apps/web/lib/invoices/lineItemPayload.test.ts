// Regression tests for the Sales Invoice / Credit Note line payload mapping
// (Beta-readiness Part 4) — run with:
//   node --experimental-strip-types --test lib/invoices/lineItemPayload.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { toInvoiceLinePayload } from "./lineItemPayload.ts";

test("sends gst_rate_percent (the field InvoiceLineIn actually declares), never gst_rate_bps", () => {
  const payload = toInvoiceLinePayload({ description: "Consulting", hsn_sac: "9983", qty: "2", rate: "500", gst_rate: 5 });
  assert.equal(payload.gst_rate_percent, 5);
  assert.ok(!("gst_rate_bps" in payload), "payload must not carry a gst_rate_bps field the backend silently ignores");
});

test("a non-default GST rate (not 18%) round-trips exactly, not the backend's 18% default", () => {
  assert.equal(toInvoiceLinePayload({ description: "Goods", hsn_sac: "1006", qty: "1", rate: "1000", gst_rate: 0 }).gst_rate_percent, 0);
  assert.equal(toInvoiceLinePayload({ description: "Goods", hsn_sac: "1006", qty: "1", rate: "1000", gst_rate: 28 }).gst_rate_percent, 28);
  assert.equal(toInvoiceLinePayload({ description: "Goods", hsn_sac: "1006", qty: "1", rate: "1000", gst_rate: 0.1 }).gst_rate_percent, 0.1);
});

test("rupees convert to integer paise", () => {
  const payload = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "3", rate: "150.50", gst_rate: 12 });
  assert.equal(payload.rate_paise, 15050);
  assert.equal(payload.quantity, 3);
});

test("description and hsn_sac are trimmed; blank hsn_sac becomes undefined", () => {
  const payload = toInvoiceLinePayload({ description: "  Padded  ", hsn_sac: "   ", qty: "1", rate: "10", gst_rate: 18 });
  assert.equal(payload.description, "Padded");
  assert.equal(payload.hsn_sac, undefined);
});

test("unit is trimmed; blank/omitted unit becomes undefined (server defaults to NOS)", () => {
  const withUnit = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "1", rate: "10", gst_rate: 18, unit: "  KGS  " });
  assert.equal(withUnit.unit, "KGS");
  const noUnit = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "1", rate: "10", gst_rate: 18 });
  assert.equal(noUnit.unit, undefined);
  const blankUnit = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "1", rate: "10", gst_rate: 18, unit: "   " });
  assert.equal(blankUnit.unit, undefined);
});

test("serviceCatalogueId round-trips as service_catalogue_id; omitted becomes undefined", () => {
  const picked = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "1", rate: "10", gst_rate: 18, serviceCatalogueId: "svc-1" });
  assert.equal(picked.service_catalogue_id, "svc-1");
  const notPicked = toInvoiceLinePayload({ description: "Item", hsn_sac: "", qty: "1", rate: "10", gst_rate: 18 });
  assert.equal(notPicked.service_catalogue_id, undefined);
});
