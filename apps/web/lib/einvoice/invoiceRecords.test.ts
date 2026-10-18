import { test } from "node:test";
import assert from "node:assert/strict";
import { INVOICE_RECORDS_WINDOW, recordsReadNote, recordsUrl } from "./invoiceRecords.ts";
import { readWindow } from "../lists/readWindow.ts";

test("the URL asks for one invoice's records and says which client", () => {
  assert.equal(
    recordsUrl("einvoice", "c 1", { salesInvoiceId: "inv/9", limit: INVOICE_RECORDS_WINDOW }),
    "/api/einvoice/records?client_id=c+1&sales_invoice_id=inv%2F9&limit=100",
  );
  assert.equal(recordsUrl("eway-bill", "c1", { salesInvoiceId: "i1" }), "/api/eway-bill/records?client_id=c1&sales_invoice_id=i1");
});

test("a URL with no invoice is the client's whole list, with no invoice parameter", () => {
  assert.equal(recordsUrl("einvoice", "c1"), "/api/einvoice/records?client_id=c1");
  assert.equal(recordsUrl("einvoice", "c1", { limit: 200 }), "/api/einvoice/records?client_id=c1&limit=200");
});

const whole = readWindow({ records: [{ id: "a" }], has_more: false, limit: 100, max_limit: 500 }, "records", 100);
const cut = readWindow({ records: [{ id: "a" }], has_more: true, limit: 100, max_limit: 500 }, "records", 100);

test("two whole reads say nothing", () => {
  assert.equal(recordsReadNote(whole, whole), null);
});

test("a read that failed is named, and an empty panel is not left to say 'none'", () => {
  assert.match(recordsReadNote(null, whole) ?? "", /e-invoice records could not be read/);
  assert.match(recordsReadNote(whole, null) ?? "", /e-way bill records could not be read/);
  assert.match(recordsReadNote(null, null) ?? "", /e-invoice and e-way bill records could not be read/);
});

test("a read that was cut short says so", () => {
  assert.match(recordsReadNote(whole, cut) ?? "", /more e-invoice or e-way bill records/);
});

test("a refusal or a scalar is not a window (the read failed), and a bare array from an older server is whole", () => {
  assert.equal(readWindow(null, "records", 100), null);
  assert.equal(readWindow("nope", "records", 100), null);
  assert.equal(recordsReadNote(readWindow([{ id: "a" }], "records", 100), whole), null);
});
