// Batch 3 — invoice editor validation. Run with:
//   node --experimental-strip-types --test lib/invoices/validation.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { validateInvoiceEditor, validateInvoiceNo, isValidLine } from "./gst.ts";
import type { InvoiceLine } from "./gst.ts";

const line = (over: Partial<InvoiceLine> = {}): InvoiceLine => ({
  description: "Consulting", hsn_sac: "", qty: "1", rate: "1000", gst_rate: 18, unit: "",
  serviceCatalogueId: "SVC-1", ...over,
});

test("a complete INR invoice validates", () => {
  const v = validateInvoiceEditor({ customerId: "c1", invoiceNo: "INV-0001", invoiceDate: "2026-07-06", lines: [line()], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, true);
  assert.equal(v.validLineCount, 1);
  assert.deepEqual(v.errors, {});
});

test("missing customer / invoiceNo / date / lines each surface an error", () => {
  const v = validateInvoiceEditor({ customerId: "", invoiceNo: "", invoiceDate: "", lines: [line({ description: "", rate: "0" })], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, false);
  assert.ok(v.errors.customer && v.errors.invoiceNo && v.errors.invoiceDate && v.errors.lines);
});

// CGST Rule 46(b): serial number, <=16 chars, letters/digits/-// only.
test("validateInvoiceNo enforces CGST Rule 46(b) shape", () => {
  assert.equal(validateInvoiceNo("INV-0001"), undefined);
  assert.equal(validateInvoiceNo("INV/2026/0001"), undefined);
  assert.equal(validateInvoiceNo("0001"), undefined);
  assert.ok(validateInvoiceNo(""));
  assert.ok(validateInvoiceNo("   "));
  assert.ok(validateInvoiceNo("INVOICE-NUMBER-001")); // 19 chars, over the 16-char cap
  assert.ok(validateInvoiceNo("INV#0001")); // '#' is not an allowed special character
  assert.ok(validateInvoiceNo("INV 0001")); // spaces not allowed
});

test("a line needs description + positive qty + positive rate + a Product/Service", () => {
  assert.equal(isValidLine(line()), true);
  assert.equal(isValidLine(line({ description: "  " })), false);
  assert.equal(isValidLine(line({ qty: "0" })), false);
  assert.equal(isValidLine(line({ rate: "0" })), false);
  assert.equal(isValidLine(line({ rate: "" })), false);
  assert.equal(isValidLine(line({ serviceCatalogueId: null })), false);
  assert.equal(isValidLine(line({ serviceCatalogueId: undefined })), false);
});

test("an invoice with no Product/Service on its only line is rejected", () => {
  const v = validateInvoiceEditor({
    customerId: "c1", invoiceNo: "INV-0001", invoiceDate: "2026-07-06",
    lines: [line({ serviceCatalogueId: null })], isForeign: false, exchangeRate: "",
  });
  assert.equal(v.ok, false);
  assert.ok(v.errors.lines);
});

test("foreign invoice requires a positive exchange rate", () => {
  assert.ok(validateInvoiceEditor({ customerId: "c1", invoiceNo: "INV-0001", invoiceDate: "2026-07-06", lines: [line()], isForeign: true, exchangeRate: "" }).errors.exchangeRate);
  assert.equal(validateInvoiceEditor({ customerId: "c1", invoiceNo: "INV-0001", invoiceDate: "2026-07-06", lines: [line()], isForeign: true, exchangeRate: "83.2" }).ok, true);
});
