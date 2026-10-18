import test from "node:test";
import assert from "node:assert/strict";
import { describeRecord } from "./recordRow.ts";

test("a prepared record sends the CA to the invoice to record the IRN", () => {
  const row = describeRecord({ status: "draft", sales_invoice_id: "inv-1" });
  assert.equal(row.linked, true);
  assert.equal(row.openLabel, "Open invoice to record the IRN");
  assert.match(row.line, /IRP portal/);
});

test("a recorded IRN and a cancelled one each say so and open the invoice", () => {
  const generated = describeRecord({ status: "generated", irn: "x".repeat(64), sales_invoice_id: "inv-1" });
  assert.equal(generated.openLabel, "Open invoice");
  assert.match(generated.line, /recorded against the invoice/);
  const cancelled = describeRecord({ status: "cancelled", sales_invoice_id: "inv-1" });
  assert.equal(cancelled.openLabel, "Open invoice");
  assert.match(cancelled.line, /cancellation recorded/);
});

test("a record that names no invoice says so and offers nothing to open", () => {
  for (const sales_invoice_id of [null, undefined, "", "   "]) {
    const row = describeRecord({ status: "generated", sales_invoice_id });
    assert.equal(row.linked, false, `id ${JSON.stringify(sales_invoice_id)}`);
    assert.equal(row.openLabel, null);
    assert.match(row.line, /no invoice in this product/);
  }
});

test("a cancelled record with no invoice is not described as awaiting an IRN", () => {
  const row = describeRecord({ status: "cancelled", sales_invoice_id: null });
  assert.match(row.line, /^Cancelled/);
  assert.doesNotMatch(row.line, /IRP portal/);
});

test("an unknown status is treated as a prepared record, the state that asks for the next step", () => {
  const row = describeRecord({ status: undefined, sales_invoice_id: "inv-1" });
  assert.equal(row.openLabel, "Open invoice to record the IRN");
});
