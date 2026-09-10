/**
 * Applying a receipt to invoices — the arithmetic, pure and testable.
 *
 * SALES-14. `PATCH /api/receipts/{id}/allocate` has existed and been correct
 * since task H3 and no screen called it, so a customer's advance could never be
 * applied to the invoice it was for. Nothing here decides anything the server
 * does not re-decide: these are the caps that stop a CA typing a figure the
 * endpoint will refuse, written down once so the modal and the receipts table
 * cannot disagree about what "unallocated" means.
 *
 * Integer paise throughout. No division except at the display boundary, which
 * is not in this file.
 */

export interface ReceiptLike {
  amount_paise: number;
  /** Customer-deducted TDS. */
  tds_paise?: number | null;
  allocated_paise?: number | null;
  /** What the SERVER recorded. Preferred over any subtraction done here. */
  unallocated_paise?: number | null;
}

/**
 * What the receipt SETTLES — cash plus the tax the customer deducted.
 *
 * A §194J receipt of ₹98,000 cash and ₹2,000 TDS settles ₹1,00,000 of
 * invoices, and routers/receipts.py caps allocations on exactly that. Capping
 * on cash alone makes a screen refuse what the server accepts, and leaves the
 * TDS permanently unallocated on an invoice that is fully paid.
 */
export function settlementValue(r: ReceiptLike): number {
  return Number(r.amount_paise ?? 0) + Number(r.tds_paise ?? 0);
}

/**
 * What is still unallocated on a receipt.
 *
 * THE STORED FIGURE FIRST. The receipts table used to compute
 * `amount − allocated`, which is a different number whenever TDS was deducted:
 * a fully-applied §194J receipt showed −₹2,000 unallocated and sat under the
 * "Unallocated only" filter for ever. The fallback is the server's own formula,
 * for a row written before the column was populated.
 */
export function unallocatedOf(r: ReceiptLike): number {
  if (r.unallocated_paise !== undefined && r.unallocated_paise !== null) {
    return Number(r.unallocated_paise);
  }
  return settlementValue(r) - Number(r.allocated_paise ?? 0);
}

export interface AllocatableInvoice {
  id: string;
  /** The GENERATED column (migration 278): total + debit notes − paid −
   *  credited, CGST Act §34. Never recomputed in the browser. */
  outstanding_paise: number;
}

/**
 * The most this receipt may put on one invoice.
 *
 * Its live outstanding PLUS whatever THIS receipt already has on it, because
 * the endpoint reverses this receipt's prior allocations before applying the
 * new ones — so an invoice this receipt already paid in full still has room for
 * it. Omitting the add-back makes re-allocating an existing receipt impossible.
 */
export function ceilingFor(inv: AllocatableInvoice, priorFromThisReceipt = 0): number {
  return Number(inv.outstanding_paise ?? 0) + Number(priorFromThisReceipt ?? 0);
}

export interface AllocationEntry {
  invoiceId: string;
  /** null when what was typed is not an amount at all. */
  paise: number | null;
  ceiling: number;
}

export interface AllocationProblems {
  /** Per invoice, in the order given. */
  perLine: { invoiceId: string; message: string }[];
  /** More than the receipt settles. */
  overRun: boolean;
  total: number;
  ok: boolean;
}

export function allocationProblems(
  entries: AllocationEntry[], settlement: number,
): AllocationProblems {
  const perLine: { invoiceId: string; message: string }[] = [];
  let total = 0;
  for (const e of entries) {
    if (e.paise === null) {
      perLine.push({ invoiceId: e.invoiceId, message: "Not an amount." });
      continue;
    }
    if (e.paise < 0) {
      // A negative allocation is not a refund — it would drive the invoice's
      // paid_paise DOWN and reopen an invoice this receipt never touched.
      perLine.push({ invoiceId: e.invoiceId, message: "Cannot be negative." });
      continue;
    }
    if (e.paise > e.ceiling) {
      perLine.push({ invoiceId: e.invoiceId, message: "More than this invoice still owes." });
    }
    total += e.paise;
  }
  const overRun = total > settlement;
  return { perLine, overRun, total, ok: perLine.length === 0 && !overRun };
}
