// Batch 2 — invoice workspace navigation + deep-link helpers. Run with:
//   node --experimental-strip-types --test lib/invoices/workspaceNav.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  salesListHref, newInvoiceHref, editInvoiceHref, parseInvoiceParam, withInvoiceParam,
  practiceSalesHref, PRACTICE_SALES_TAB_IDS,
} from "./workspaceNav.ts";

test("route href builders", () => {
  assert.equal(salesListHref("CL-1"), "/clients/CL-1/sales");
  assert.equal(newInvoiceHref("CL-1"), "/clients/CL-1/sales/invoices/new/edit");
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

// PRE-A-018 — the practice's fee screens link into the practice client's sales workspace.
test("practiceSalesHref fails closed: no usable id, no link", () => {
  for (const bad of [null, undefined, "", " ", "\t\n", "_placeholder", " _placeholder ", 42, {}, [], true]) {
    assert.equal(practiceSalesHref(bad), null, `id ${JSON.stringify(bad)}`);
    assert.equal(practiceSalesHref(bad, { tab: "receipts" }), null);
    assert.equal(practiceSalesHref(bad, { invoiceId: "abc" }), null);
  }
});

test("practiceSalesHref opens the practice's Sales list, a tab, or one invoice", () => {
  assert.equal(practiceSalesHref("abc"), "/clients/abc/sales");
  assert.equal(practiceSalesHref("abc"), salesListHref("abc"));
  assert.equal(practiceSalesHref("abc", {}), "/clients/abc/sales");
  assert.equal(practiceSalesHref("abc", { tab: "receipts" }), "/clients/abc/sales?tab=receipts");
  assert.equal(practiceSalesHref("abc", { invoiceId: "inv-1" }), "/clients/abc/sales?invoice=inv-1");
  assert.equal(practiceSalesHref("abc", { invoiceId: "inv-1" }), withInvoiceParam("/clients/abc/sales", "", "inv-1"));
  // The id is trimmed, not rejected for stray whitespace the server never sends.
  assert.equal(practiceSalesHref("  abc  "), "/clients/abc/sales");
});

test("practiceSalesHref: a blank invoice id is no invoice, and a tab outranks an invoice", () => {
  assert.equal(practiceSalesHref("abc", { invoiceId: null }), "/clients/abc/sales");
  assert.equal(practiceSalesHref("abc", { invoiceId: "" }), "/clients/abc/sales");
  assert.equal(practiceSalesHref("abc", { invoiceId: "   " }), "/clients/abc/sales");
  // The drawer belongs to the Invoices tab, so asking for both opens the tab only.
  assert.equal(practiceSalesHref("abc", { tab: "receipts", invoiceId: "inv-1" }), "/clients/abc/sales?tab=receipts");
  // A tab nobody listed is not emitted (the type forbids it; a cast must not slip it through).
  assert.equal(practiceSalesHref("abc", { tab: "ledger" as never }), "/clients/abc/sales");
});

test("practiceSalesHref encodes what it is given", () => {
  assert.equal(practiceSalesHref("a/b?c#d"), "/clients/a%2Fb%3Fc%23d/sales");
  assert.equal(practiceSalesHref("abc", { invoiceId: "a b&c=d" }), "/clients/abc/sales?invoice=a+b%26c%3Dd");
  // The fixed id shape the server sends is untouched.
  const uuid = "0f8fad5b-d9cb-469f-a165-70867728950e";
  assert.equal(practiceSalesHref(uuid), `/clients/${uuid}/sales`);
});

test("every tab a practice screen can ask for is one practiceSalesHref emits", () => {
  for (const tab of PRACTICE_SALES_TAB_IDS) {
    assert.equal(practiceSalesHref("abc", { tab }), `/clients/abc/sales?tab=${tab}`);
  }
});
