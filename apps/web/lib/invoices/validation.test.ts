// Batch 3 — invoice editor validation. Run with:
//   node --experimental-strip-types --test lib/invoices/validation.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { validateInvoiceEditor, isValidLine } from "./gst.ts";
import type { InvoiceLine } from "./gst.ts";

const line = (over: Partial<InvoiceLine> = {}): InvoiceLine => ({
  description: "Consulting", hsn_sac: "", qty: "1", rate: "1000", gst_rate: 18, ...over,
});

test("a complete INR invoice validates", () => {
  const v = validateInvoiceEditor({ customerId: "c1", invoiceDate: "2026-07-06", lines: [line()], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, true);
  assert.equal(v.validLineCount, 1);
  assert.deepEqual(v.errors, {});
});

test("missing customer / date / lines each surface an error", () => {
  const v = validateInvoiceEditor({ customerId: "", invoiceDate: "", lines: [line({ description: "", rate: "0" })], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, false);
  assert.ok(v.errors.customer && v.errors.invoiceDate && v.errors.lines);
});

test("a line needs description + positive qty + positive rate", () => {
  assert.equal(isValidLine(line()), true);
  assert.equal(isValidLine(line({ description: "  " })), false);
  assert.equal(isValidLine(line({ qty: "0" })), false);
  assert.equal(isValidLine(line({ rate: "0" })), false);
  assert.equal(isValidLine(line({ rate: "" })), false);
});

test("foreign invoice requires a positive exchange rate", () => {
  assert.ok(validateInvoiceEditor({ customerId: "c1", invoiceDate: "2026-07-06", lines: [line()], isForeign: true, exchangeRate: "" }).errors.exchangeRate);
  assert.equal(validateInvoiceEditor({ customerId: "c1", invoiceDate: "2026-07-06", lines: [line()], isForeign: true, exchangeRate: "83.2" }).ok, true);
});
