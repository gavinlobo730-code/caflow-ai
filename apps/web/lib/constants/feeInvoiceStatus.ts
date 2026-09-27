/**
 * The practice's OWN fee invoices (`public.fee_invoices`) — which statuses
 * exist, and which of them are OWED.
 *
 * `FEE_INVOICE_STATUSES` is migration 123's `fee_invoices_status_check`,
 * verbatim and in its order: Draft, Issued, Sent, Paid, Overdue, Cancelled.
 * `feeInvoiceStatus.test.ts` reads the CHECK out of the migrations directory
 * and fails if the two part company, so a status added there has to be placed
 * on one side of the owed line below before anything builds.
 *
 * OWED is Issued, Sent and Overdue — an invoice the client has been sent and
 * has not settled. "Sent" is the table's ORIGINAL spelling of Issued, kept by
 * migration 123 for rows written before it, and a row carrying it is owed
 * exactly as much. NOT owed:
 *   · Draft     — nobody has been sent it, so nothing is due on it yet;
 *   · Paid      — settled (record_fee_receipt_atomic sets it once receipts
 *                 cover the total, migration 172);
 *   · Cancelled — withdrawn.
 *
 * WHY THIS IS ONE CONSTANT: /billing asked the question three ways at once.
 * Aged Debtors kept `status !== "Paid"`, so a Draft — and a Cancelled invoice —
 * aged as a debt and got a WhatsApp "Remind" link sending the client a demand
 * for fees nobody had billed; the Outstanding tile counted `"Issued"` alone,
 * so an Overdue or a Sent invoice was owed on one tab and not on the other;
 * and the receipt picker offered Drafts and Cancelled invoices to record money
 * against. The backend serves no such set (the fee-invoice endpoints return
 * rows, not a classification), so the rule lives here, once, and every reader
 * asks `isOwedFeeInvoice`.
 */

export const FEE_INVOICE_STATUSES = [
  "Draft", "Issued", "Sent", "Paid", "Overdue", "Cancelled",
] as const;

export type FeeInvoiceStatus = (typeof FEE_INVOICE_STATUSES)[number];

export const OWED_FEE_INVOICE_STATUSES: ReadonlySet<FeeInvoiceStatus> = new Set<FeeInvoiceStatus>([
  "Issued", "Sent", "Overdue",
]);

/** True when a fee invoice in this status is money the client owes the firm. */
export function isOwedFeeInvoice(status: string | null | undefined): boolean {
  return status != null && (OWED_FEE_INVOICE_STATUSES as ReadonlySet<string>).has(status);
}
