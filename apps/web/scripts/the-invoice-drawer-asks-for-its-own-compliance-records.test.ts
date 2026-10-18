// POST-A-263. The invoice drawer found an invoice's e-invoice and e-way bill records by reading ALL of the client's, newest
// first, with no limit, and looking for its invoice among them. The two list routes take `sales_invoice_id` now and answer a
// window; the drawer asks for its own invoice's, reads the window through the shared reader and says when a read did not come
// back whole, and the e-invoice screen says when ITS list stopped short.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-invoice-drawer-asks-for-its-own-compliance-records.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

function* walk(dir: string): Generator<string> {
  for (const name of fs.readdirSync(dir)) {
    if (["node_modules", ".next", "out", ".git"].includes(name)) continue;
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) yield* walk(p);
    else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) yield p;
  }
}

test("the drawer asks for this invoice's records by invoice, in a window, and reads them through the shared reader", () => {
  const code = read("components/invoices/InvoiceViewDrawer.tsx");
  assert.match(code, /recordsUrl\("einvoice", clientId, ask\)/);
  assert.match(code, /recordsUrl\("eway-bill", clientId, ask\)/);
  assert.match(code, /salesInvoiceId: invoiceId/, "the read does not name the invoice");
  assert.match(code, /readWindow<EInvoiceRecord>\(/);
  assert.match(code, /readWindow<EWayRecord>\(/);
  assert.match(code, /recordsReadNote\(eiWin, ewWin\)/, "a read that did not come back whole is not said");
  assert.doesNotMatch(code, /\(ei\.data as EInvoiceRecord\[\]\)/, "the drawer reads the client's list as a bare array again");
});

test("nothing outside the URL builder spells the client-wide records read", () => {
  const offenders: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const file of walk(path.join(WEB, dir))) {
      const rel = path.relative(WEB, file);
      if (rel === path.join("lib", "einvoice", "invoiceRecords.ts")) continue;
      if (/\/api\/(einvoice|eway-bill)\/records\?/.test(stripComments(fs.readFileSync(file, "utf8")))) offenders.push(rel);
    }
  }
  assert.deepEqual(offenders, [], "a file builds the records-list URL itself; use recordsUrl() so the invoice filter and the window cannot be forgotten");
});

test("the e-invoice screen reads the window and says when the list stopped short", () => {
  const code = read("app/einvoice/page.tsx");
  assert.match(code, /readWindow<EInvoiceRecord>\(/);
  assert.match(code, /<ListWindowNotice/);
  assert.doesNotMatch(code, /arrayOrEmpty<EInvoiceRecord>/, "the screen takes the server's answer for a bare array again");
});

test("the rule finds the client-wide spelling (negative control)", () => {
  const bad = "apiGet(`/api/einvoice/records?client_id=${clientId}`, token)";
  const fine = 'apiGet(recordsUrl("einvoice", clientId, ask), token); apiPost("/api/einvoice/records", body)';
  assert.equal(/\/api\/(einvoice|eway-bill)\/records\?/.test(bad), true);
  assert.equal(/\/api\/(einvoice|eway-bill)\/records\?/.test(fine), false);
});
