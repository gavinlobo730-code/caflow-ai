/**
 * What a row of the firm-level e-invoice list says about one IRN record
 * (POST-A-065).
 *
 * A record belongs on an invoice. The invoice's own compliance panel is where one
 * is prepared (it reads the invoice's GST treatment and refuses a record that
 * contradicts it) and where its IRN is recorded, so this list only SHOWS records
 * and says, for each, where the next step happens. A record that names no
 * invoice in this product is said so in words rather than rendered as an ordinary
 * one: nothing can attach its IRN to an invoice, and the worklist of invoices
 * that still need an IRN cannot see it. The server accepts such a record (an
 * invoice raised outside the product), and one exists, so the list has to be
 * able to show it.
 *
 * Relative imports only: node loads this file directly in the unit tests.
 */

export type RecordLike = {
  status?: string | null;
  irn?: string | null;
  sales_invoice_id?: string | null;
};

export type RecordRow = {
  /** Whether the record names an invoice this product holds. */
  linked: boolean;
  /** The one sentence under the invoice number saying what stands. */
  line: string;
  /** What the link beside the row says, or null where the row has no invoice to open. */
  openLabel: string | null;
};

export function describeRecord(r: RecordLike): RecordRow {
  const linked = Boolean(r.sales_invoice_id && String(r.sales_invoice_id).trim());
  const status = (r.status ?? "").toLowerCase();

  if (!linked) {
    return {
      linked: false,
      line: status === "cancelled"
        ? "Cancelled. It named no invoice in this product."
        : "Names no invoice in this product, so no invoice here shows this IRN and the list of invoices that still need one cannot count it.",
      openLabel: null,
    };
  }
  if (status === "generated") {
    return { linked: true, line: "IRN recorded against the invoice.", openLabel: "Open invoice" };
  }
  if (status === "cancelled") {
    return { linked: true, line: "IRN cancellation recorded against the invoice.", openLabel: "Open invoice" };
  }
  return {
    linked: true,
    line: "Prepared. Generate the IRN on the IRP portal, then record it on the invoice.",
    openLabel: "Open invoice to record the IRN",
  };
}
