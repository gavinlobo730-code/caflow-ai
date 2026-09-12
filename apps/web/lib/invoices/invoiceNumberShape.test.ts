import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateInvoiceNo } from "./gst.ts";

/**
 * The browser mirror of apps/api/domain/gst/invoice_series.format_violation,
 * exercised on the SAME cases the Python authority is —
 * apps/api/tests/fixtures/invoice_number.json, read by both suites. Changing
 * one implementation without the other fails here.
 *
 * The two word their refusals differently on purpose (the server names the
 * character it found; the browser tells a CA mid-keystroke what is allowed),
 * so only the VERDICT is pinned, never the message. Nothing here should ever
 * grow an expectation about wording — that is how a mirror starts being
 * maintained as if it were the rule.
 */
const SHARED = JSON.parse(
  readFileSync(new URL("../../../api/tests/fixtures/invoice_number.json", import.meta.url), "utf8"),
) as {
  legal: string[];
  illegal: { number: string; why: string }[];
};

test("every shared legal invoice number is accepted", () => {
  for (const n of SHARED.legal) {
    assert.equal(validateInvoiceNo(n), undefined,
      `${JSON.stringify(n)} should be legal under CGST Rule 46(b)`);
  }
});

test("every shared illegal invoice number is refused", () => {
  for (const c of SHARED.illegal) {
    assert.ok(validateInvoiceNo(c.number),
      `${JSON.stringify(c.number)} should be refused — ${c.why}`);
  }
});

test("the fixture is not empty in either direction", () => {
  // A fixture that silently emptied would make both tests above pass while
  // pinning nothing at all.
  assert.ok(SHARED.legal.length >= 10);
  assert.ok(SHARED.illegal.length >= 8);
});
