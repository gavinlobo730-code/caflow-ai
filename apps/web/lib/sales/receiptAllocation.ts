/**
 * Applying a RECEIPT to invoices — what a receipt has to give, and how much.
 *
 * SALES-14. `PATCH /api/receipts/{id}/allocate` has existed and been correct
 * since task H3 and no screen called it, so a customer's advance could never be
 * applied to the invoice it was for. Nothing here decides anything the server
 * does not re-decide: these are the caps that stop a CA typing a figure the
 * endpoint will refuse, written down once so the modal and the receipts table
 * cannot disagree about what "unallocated" means.
 *
 * THE CAPS THEMSELVES MOVED to `lib/allocation/documentAllocation` on
 * 24-09-2026, when the AP mirror was finally wired up — `PATCH
 * /api/purchase-payments/{id}/allocate`, written at the same time as this one
 * and equally uncalled. The two servers do the same thing, so the two screens
 * apply the same caps, and two copies would drift. They are re-exported here so
 * every existing importer is untouched.
 *
 * WHAT STAYS IS THE PART THAT IS NOT SHARED: what a RECEIPT settles. That is a
 * statutory question with a different answer on each side, and it is the one
 * thing neither module may take from the other.
 *
 * Integer paise throughout. No division except at the display boundary, which
 * is not in this file.
 */

export {
  ceilingFor,
  allocationProblems,
  type AllocatableDocument,
  type AllocatableDocument as AllocatableInvoice,
  type AllocationEntry,
  type AllocationProblems,
} from "../allocation/documentAllocation.ts";

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
 *
 * THE AP SIDE IS NOT THIS. A vendor payment settles the cash and only the
 * cash — see `lib/purchases/paymentAllocation.settlementValue`, which says why.
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
