/**
 * Applying a VENDOR PAYMENT to bills — what a payment has to give, and how much.
 *
 * THE AP MIRROR OF SALES-14, AND IT WAS UNREACHABLE FOR EXACTLY AS LONG.
 * `PATCH /api/purchase-payments/{payment_id}/allocate` was written at the same
 * time as the AR one — `purchase_payment_service.update_allocations_core`'s own
 * docstring calls itself "the AP mirror of receipts.py" and names the two cases
 * it exists for: an advance stranded by a bank-match settlement that exceeded
 * the bills it was told about, and a payment recorded before the bill it is
 * meant for existed. Neither could ever be resolved, because nothing in
 * `apps/web` called it. The Purchases screen showed an unallocated figure only
 * while a payment was being TYPED — a running total in the form — and never
 * again once it was saved.
 *
 * The CAPS are `lib/allocation/documentAllocation`, shared with the AR side
 * because both servers do the same thing. What is here is the one thing that is
 * NOT shared.
 *
 * Integer paise throughout. No division except at the display boundary.
 */

export {
  ceilingFor,
  allocationProblems,
  type AllocatableDocument,
  type AllocatableDocument as AllocatableBill,
  type AllocationEntry,
  type AllocationProblems,
} from "../allocation/documentAllocation.ts";

export interface PaymentLike {
  amount_paise: number;
  allocated_paise?: number | null;
  /** What the SERVER recorded. Preferred over any subtraction done here. */
  unallocated_paise?: number | null;
}

/**
 * What the payment SETTLES — the cash, and **only** the cash.
 *
 * THE AR SIDE ADDS TDS AND THIS ONE MUST NOT, and the asymmetry is real rather
 * than an oversight on either side. On a RECEIPT the tax was deducted by the
 * CUSTOMER out of what they owed us; IT Act §198 deems it received and §199
 * gives credit for it, so ₹98,000 of cash with ₹2,000 of §194J settles a
 * ₹1,00,000 invoice and `routers/receipts.py` caps on the sum. On a PAYMENT the
 * tax is deducted by the CLIENT out of what they owe the vendor, and it has
 * already come off the bill: `purchase_bills.net_payable_paise` is what is
 * payable after withholding, which is the figure migration 278's generated
 * `outstanding_paise` is built from. Adding it again here would let a CA apply
 * ₹1,00,000 of a ₹98,000 payment and have the server answer 422 — the server
 * caps on `amount_paise` alone, and a screen that disagrees with it teaches the
 * CA to distrust the screen.
 *
 * Kept as a function rather than read inline so the rule has a place to be
 * read, and so the two sides' definitions sit side by side in the diff that
 * ever changes one of them.
 */
export function settlementValue(p: PaymentLike): number {
  return Number(p.amount_paise ?? 0);
}

/**
 * What is still unallocated on a payment.
 *
 * THE STORED FIGURE FIRST — `update_allocations_core` writes
 * `unallocated_paise = amount_paise − Σ allocated` at the end of every
 * re-allocation, and `create_payment_core` writes it at creation, so the column
 * is the server's own answer. The fallback is that same formula, for a row
 * written before the column existed.
 */
export function unallocatedOf(p: PaymentLike): number {
  if (p.unallocated_paise !== undefined && p.unallocated_paise !== null) {
    return Number(p.unallocated_paise);
  }
  return settlementValue(p) - Number(p.allocated_paise ?? 0);
}
