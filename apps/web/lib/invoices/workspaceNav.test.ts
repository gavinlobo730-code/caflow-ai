// Batch 2 — invoice workspace navigation + deep-link helpers. Run with:
//   node --experimental-strip-types --test lib/invoices/workspaceNav.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  salesListHref, newInvoiceHref, editInvoiceHref, parseInvoiceParam, withInvoiceParam,
} from "./workspaceNav.ts";

test("route href builders", () => {
  assert.equal(salesListHref("CL-1"), "/clients/CL-1/sales");
  assert.equal(newInvoiceHref("CL-1"), "/clients/CL-1/sales/invoices/new");
  assert.equal(editInvoiceHref("CL-1", "INV-9"), "/clients/CL-1/sales/invoices/INV-9/edit");
});

test("parseInvoiceParam reads ?invoice= (null when absent/blank)", () => {
  assert.equal(parseInvoiceParam("?invoice=abc"), "abc");
  assert.equal(parseInvoiceParam("?foo=1&invoice=xyz"), "xyz");
  assert.equal(parseInvoiceParam(""), null);
  assert.equal(parseInvoiceParam("?invoice="), null);
  assert.equal(parseInvoiceParam("?other=1"), null);
});

test("withInvoiceParam sets/removes invoice while preserving other params", () => {
  assert.equal(withInvoiceParam("/p", "?fy=previous", "abc"), "/p?fy=previous&invoice=abc");
  assert.equal(withInvoiceParam("/p", "?invoice=old&fy=previous", null), "/p?fy=previous");
  assert.equal(withInvoiceParam("/p", "?invoice=old", null), "/p");
  assert.equal(withInvoiceParam("/p", "", "abc"), "/p?invoice=abc");
});
