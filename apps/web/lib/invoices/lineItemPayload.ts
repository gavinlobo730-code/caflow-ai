/**
 * Shared line-item → API-payload mapping for Sales Invoices and Credit Notes
 * (Beta-readiness Part 4). Both forms build lines from the same percentage-based
 * shape (qty/rate as strings, gst_rate as a plain percentage like 18) and send
 * them to endpoints whose lines are InvoiceLineIn (apps/api/models/invoices.py),
 * which declares gst_rate_percent — NOT gst_rate_bps. A previous gst_rate_bps
 * field on this payload was silently dropped by Pydantic, so every line fell
 * back to the model's 18% default regardless of the rate actually picked in
 * the UI. Centralizing the mapping here means the correct field name only has
 * to be right once.
 */

import { ratePaiseFromRupees } from "../money/gstLine.ts";
import { bpsFromPercentInput } from "../money/rupeeInput.ts";

export interface InvoiceLineInput {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // rupees
  gst_rate: number; // percentage, e.g. 18
  unit?: string; // UQC, e.g. "NOS", "KGS"; blank -> server default "NOS"
  /**
   * Which service_catalogue preset this line was picked from — mandatory on
   * every line (migration 206), and also the traceability link for the
   * Products & Services delete-guard (migration 184). Never read by any GST/
   * journal computation.
   */
  serviceCatalogueId?: string | null;
  /**
   * A §15(3)(a) discount as a PERCENTAGE, as typed. Sales invoices only —
   * `SalesInvoiceLineIn` is the model that has it, and the credit/debit note
   * models deliberately do not (§15(3)(b) is the note itself, not a field on
   * one). Passing it on a note payload is simply dropped by Pydantic, which is
   * the same silent-drop trap this module's header describes; the note editors
   * never set it.
   */
  discountPercent?: string;
}

export interface InvoiceLinePayload {
  description: string;
  hsn_sac: string | undefined;
  quantity: number;
  rate_paise: number;
  gst_rate_percent: number;
  unit: string | undefined;
  service_catalogue_id: string | null | undefined;
  /** Basis points: 500 = 5.00%. Omitted entirely when no discount was typed —
   *  the server then charges on the whole value, which is the truth. */
  discount_percent_bps?: number;
}

export function toInvoiceLinePayload(line: InvoiceLineInput): InvoiceLinePayload {
  return {
    description: line.description.trim(),
    hsn_sac: line.hsn_sac.trim() || undefined,
    quantity: parseFloat(line.qty),
    // Shared with the preview math (lib/money/gstLine.ts) so the paise the
    // summary reasons about is byte-identical to the paise actually sent.
    rate_paise: ratePaiseFromRupees(line.rate),
    gst_rate_percent: line.gst_rate,
    unit: line.unit?.trim() || undefined,
    service_catalogue_id: line.serviceCatalogueId ?? undefined,
    // bpsFromPercentInput is the one parser (lib/money/rupeeInput.ts). It
    // REFUSES anything that is not a number rather than coercing it to 0 —
    // a discount silently read as zero is an invoice charging tax the customer
    // was told they would not pay.
    ...(discountBps(line.discountPercent) === null
      ? {}
      : { discount_percent_bps: discountBps(line.discountPercent) as number }),
  };
}

function discountBps(typed?: string): number | null {
  if (typed === undefined || typed === null || typed.trim() === "") return null;
  return bpsFromPercentInput(typed.trim());
}
