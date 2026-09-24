/**
 * Applying a payment or a receipt to the documents it settles — the
 * arithmetic, pure and testable, and the SAME arithmetic on both sides.
 *
 * WHY THIS IS ONE FILE AND NOT TWO
 *
 * SALES-14 built this for the AR side: `PATCH /api/receipts/{id}/allocate`
 * existed and was correct and no screen called it, so a customer's advance
 * could never be applied to the invoice it was for. The AP side is the exact
 * mirror — `PATCH /api/purchase-payments/{id}/allocate`, written at the same
 * time, `update_allocations_core`'s own docstring calling itself "the AP
 * mirror of receipts.py" — and it had no caller either.
 *
 * The two servers do the SAME thing: reverse this document's prior
 * allocations, re-validate every new one against the target's live
 * outstanding, re-apply, rewrite `unallocated_paise`. So the caps a screen
 * puts in front of a CA are the same too, and two copies of them would drift
 * the first time one side learned something the other did not.
 *
 * WHAT IS **NOT** SHARED, AND IT IS THE PART THAT MATTERS
 *
 * The SETTLEMENT value — how much a receipt or a payment has to give — is
 * genuinely different, and each side defines it in its own module with its own
 * reason:
 *
 *   AR (`lib/sales/receiptAllocation`)    cash **+ the TDS the customer
 *                                         deducted**. IT Act §198 deems the
 *                                         tax deducted to be income received
 *                                         and §199 gives credit for it, so a
 *                                         ₹98,000 receipt with ₹2,000 of §194J
 *                                         settles ₹1,00,000 of invoices, and
 *                                         `routers/receipts.py` caps on
 *                                         exactly that.
 *   AP (`lib/purchases/paymentAllocation`) the cash, **and only the cash**.
 *                                         `update_allocations_core` caps on
 *                                         `amount_paise` alone.
 *
 * Writing either as "the other one, but …" is how the two would end up sharing
 * a mistake. They answer different questions and each says which.
 *
 * Integer paise throughout. No division except at the display boundary, which
 * is not in this file.
 */

export interface AllocatableDocument {
  id: string;
  /** The GENERATED column (migration 278). On a sales invoice: total + debit
   *  notes − paid − credited. On a purchase bill: net payable + credit notes −
   *  paid − debited. CGST Act §34 is what puts the note terms in both, and the
   *  SIGNS are not guessable from the names — which is exactly why this is
   *  read and never recomputed in the browser. */
  outstanding_paise: number;
}

/**
 * The most this receipt or payment may put on one document.
 *
 * Its live outstanding PLUS whatever THIS document already has on it, because
 * both endpoints reverse the prior allocations before applying the new ones —
 * so an invoice this receipt already paid in full still has room for it.
 * Omitting the add-back makes re-allocating an existing receipt or payment
 * impossible, and makes the line vanish from the set the modal submits.
 */
export function ceilingFor(doc: AllocatableDocument, priorFromThisDocument = 0): number {
  return Number(doc.outstanding_paise ?? 0) + Number(priorFromThisDocument ?? 0);
}

export interface AllocationEntry {
  /** The invoice or bill being settled. Named for the ROLE rather than for
   *  one side's document, because the same function serves both. */
  documentId: string;
  /** null when what was typed is not an amount at all. */
  paise: number | null;
  ceiling: number;
}

export interface AllocationProblems {
  /** Per document, in the order given. */
  perLine: { documentId: string; message: string }[];
  /** More than the receipt or payment settles. */
  overRun: boolean;
  total: number;
  ok: boolean;
}

export function allocationProblems(
  entries: AllocationEntry[], settlement: number,
): AllocationProblems {
  const perLine: { documentId: string; message: string }[] = [];
  let total = 0;
  for (const e of entries) {
    if (e.paise === null) {
      perLine.push({ documentId: e.documentId, message: "Not an amount." });
      continue;
    }
    if (e.paise < 0) {
      // A negative allocation is not a refund — it would drive the document's
      // paid_paise DOWN and reopen one this receipt or payment never touched.
      perLine.push({ documentId: e.documentId, message: "Cannot be negative." });
      continue;
    }
    if (e.paise > e.ceiling) {
      perLine.push({ documentId: e.documentId, message: "More than this document still owes." });
    }
    total += e.paise;
  }
  const overRun = total > settlement;
  return { perLine, overRun, total, ok: perLine.length === 0 && !overRun };
}
