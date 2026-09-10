/**
 * "Outstanding" is what is still recoverable, not what was billed (SALES-05).
 *
 * WHAT WAS WRONG
 *   The Sales screen's Outstanding tile summed the GROSS total of every issued
 *   and partially-paid invoice. `paid_paise` was fetched and simply not
 *   subtracted, and `credited_paise` was not even selected. A client with
 *   ₹10,00,000 invoiced, ₹8,00,000 collected on account and ₹50,000 credited
 *   read "Outstanding ₹10,00,000" instead of ₹1,50,000 — and every partial
 *   payment and every credit note made it worse.
 *
 *   Four other places on the same page subtracted `paid_paise` and still
 *   ignored credit notes, so the §34 half of the drift was page-wide.
 *
 * WHY A RESOLVER AND NOT FIVE SUBTRACTIONS
 *   `outstanding_paise` is a GENERATED column (migration 278) — total + debit
 *   notes − paid − credited — so it cannot drift from its parts. The backend
 *   has always used it. The browser recomputing the formula is exactly what let
 *   it drift, so there is now one function and the screens call it.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { outstandingOf, type SalesInvoice } from "./gst.ts";

function inv(over: Partial<SalesInvoice>): SalesInvoice {
  return {
    id: "i1", invoice_no: "INV-1", invoice_date: "2026-06-01", due_date: null,
    customer_id: "c1", taxable_paise: 0, gst_paise: 0,
    total_paise: 10_00_000_00, status: "issued",
    supply_state_code: "27", is_interstate: false,
    ...over,
  } as SalesInvoice;
}

describe("outstandingOf", () => {
  it("is the server's generated figure when it was selected", () => {
    // The finding's own numbers: ₹10,00,000 billed, ₹8,00,000 collected,
    // ₹50,000 credited. The generated column already nets all three.
    assert.equal(
      outstandingOf(inv({ paid_paise: 8_00_000_00, outstanding_paise: 1_50_000_00 })),
      1_50_000_00,
    );
  });

  it("does NOT recompute total minus paid when the column is present", () => {
    // This is the whole point. `total − paid` here is ₹2,00,000 and the right
    // answer is ₹1,50,000; the ₹50,000 difference is a credit note the browser
    // never selected and could not have known about.
    const i = inv({ paid_paise: 8_00_000_00, outstanding_paise: 1_50_000_00 });
    assert.notEqual(outstandingOf(i), i.total_paise - (i.paid_paise ?? 0));
  });

  it("falls back to total minus paid when the column was not selected", () => {
    assert.equal(outstandingOf(inv({ paid_paise: 8_00_000_00 })), 2_00_000_00);
  });

  it("treats a missing paid_paise as nothing paid", () => {
    assert.equal(outstandingOf(inv({})), 10_00_000_00);
  });

  it("reports zero as zero rather than as falsy-and-therefore-absent", () => {
    // `outstanding_paise: 0` is a settled invoice. A truthiness check would
    // read it as "not selected" and fall through to total − paid, which on a
    // fully credited invoice is the whole invoice.
    assert.equal(outstandingOf(inv({ paid_paise: 0, outstanding_paise: 0 })), 0);
  });

  it("passes a negative figure through rather than flooring it", () => {
    // An over-collection or an over-credit is a real state and the CA needs to
    // see it. Flooring at zero here would hide it on the tile while the ledger
    // still carried it.
    assert.equal(outstandingOf(inv({ outstanding_paise: -5_000_00 })), -5_000_00);
  });
});
