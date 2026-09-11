// CGST §15(3)(a) on the sales-invoice editor. Run with:
//   node --experimental-strip-types --test scripts/a-discount-is-excluded-from-the-value-of-supply.test.ts
//
// WHY THIS EXISTS (SALES-11)
//     There was no discount concept anywhere on the sales-invoice path, so a
//     trading client giving a 5% trade discount could only have it netted into
//     the rate by hand — which loses the disclosure the customer's copy shows,
//     makes the invoice un-reconcilable to the price list, and forfeits the
//     §15(3)(a) relief, which is conditional on the discount being RECORDED IN
//     THE INVOICE.
//
//     §15(3)(b) — a discount given AFTER the supply — is a different remedy
//     entirely: it needs a pre-supply agreement, linkage to the invoices, and
//     the recipient's ITC reversal, and it is the §34 credit note itself. The
//     note editors must not grow a discount control, and test 5 holds that.
//
// WHAT IS ASSERTED
//     1. The arithmetic lives in the one mirrored module and is not re-done in
//        the component. Two implementations of a value-of-supply rule is how a
//        preview comes to disagree with what the server saves.
//     2. Every typed number goes through lib/money — the one parser — so a
//        discount is never silently coerced to 0.
//     3. The discount is visible: a Disc % column, a bill-level control, and a
//        summary that shows gross, deduction and net rather than only the net.
//     4. It reaches the payload, and it is rehydrated on edit — update_invoice
//        deletes and reinserts every line, so a discount the editor did not
//        carry would be dropped on the next save.
//     5. The credit and debit note editors have no discount anything.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const EDITOR = readFileSync("components/invoices/InvoiceEditor.tsx", "utf8");
const PAYLOAD = readFileSync("lib/invoices/lineItemPayload.ts", "utf8");
const GST = readFileSync("lib/invoices/gst.ts", "utf8");

test("the arithmetic is the mirrored module's, not the component's", () => {
  // gstLine.ts is pinned to apps/api/domain/gst/discount.py by
  // shared/gst-parity-vectors.json. A second implementation in the component
  // would not be.
  assert.match(GST, /applyDiscountsToLines/,
    "computeGst must resolve discounts through the mirrored module");
  assert.doesNotMatch(EDITOR, /\/\s*10000\b/,
    "basis points must not be converted to a fraction in the component");
  assert.doesNotMatch(EDITOR, /gross[_ ]?\*\s*(pct|percent)/i,
    "the component must not compute a discount of its own");
});

test("every typed number goes through the one parser", () => {
  assert.match(EDITOR, /bpsFromPercentInput\(raw\)/,
    "a typed percentage must go through bpsFromPercentInput");
  assert.match(EDITOR, /paiseFromRupeeInput\(raw\)/,
    "a typed amount must go through paiseFromRupeeInput");
  assert.match(PAYLOAD, /bpsFromPercentInput\(typed\.trim\(\)\)/,
    "the payload builder must too");
  // The trap this replaced: parseFloat("2,5") is 2, parseFloat("") is NaN, and
  // a discount silently read as zero is an invoice charging tax the customer
  // was told they would not pay.
  assert.doesNotMatch(PAYLOAD, /parseFloat\([^)]*discount/i);
});

test("the discount is on the face of the screen", () => {
  assert.match(EDITOR, />Disc %</, "the line table needs a Disc % column");
  assert.match(EDITOR, /aria-label=\{`Line \$\{idx \+ 1\} discount percent`\}/,
    "and the cell must be labelled");
  assert.match(EDITOR, /id="inv-doc-discount"/,
    "the bill-level discount needs a control");
  assert.match(EDITOR, /label="Gross value"/,
    "§15(3)(a) relief is conditional on the invoice RECORDING the discount, so the gross is shown");
  assert.match(EDITOR, /label="Less: discount"/,
    "…and the deduction beside it");
});

test("it reaches the payload and survives a re-edit", () => {
  assert.match(PAYLOAD, /discount_percent_bps/,
    "the line payload must carry the discount");
  assert.match(EDITOR, /docDiscountPayload/,
    "the document discount must reach the request body");
  // One of percent or amount, never both: the server takes the percentage when
  // both arrive, and sending a derived amount beside a typed percentage is how
  // a form's preview becomes the document.
  assert.match(EDITOR, /discount_percent_bps: documentDiscount\.percentBps/);
  assert.match(EDITOR, /discount_paise: documentDiscount\.amountPaise/);
  // update_invoice deletes and reinserts every line.
  assert.match(EDITOR, /discountPercent: l\.discount_percent_bps == null/,
    "a line discount must be rehydrated on edit or the next save drops it");
  assert.match(EDITOR, /src\.discount_percent_bps != null/,
    "so must the bill-level one");
});

test("a credit or debit note has no discount anything", () => {
  // §15(3)(b): a post-supply discount needs a pre-supply agreement, linkage to
  // the invoices, and the recipient's ITC reversal. It IS the §34 note, not a
  // field on one — and the backend model the note editors post to has no such
  // field, so a control here would be a control that silently does nothing.
  for (const f of [
    "components/sales/SalesCreditNoteEditor.tsx",
    "components/sales/SalesDebitNoteEditor.tsx",
  ]) {
    const src = readFileSync(f, "utf8");
    assert.doesNotMatch(src, /discount/i, `${f} must not offer a discount`);
  }
});
