/**
 * The server's "raise an invoice from this order" answer, in the shape the invoice editor seeds from (POST-A-104).
 *
 * THIS DECIDES NOTHING. Which lines, what quantity, which order line each bills, and what the CA should read first are the server's
 * (`sales_cycle_service.invoice_seed_from_order`). This only fills the fields an unsaved invoice does not have yet with the values a
 * new invoice starts with: no number, no date, nothing paid, a draft. The quantity is read with the one quantity parser; a quantity it
 * cannot read is refused, never guessed.
 */
import type { OrderInvoiceSeed } from "@/lib/api";
import type { InvoiceDetail } from "@/lib/invoices/shared";
import { parseQuantity } from "../money/rupeeInput.ts";

export function invoiceDetailFromOrderSeed(answer: OrderInvoiceSeed): InvoiceDetail | null {
  const lines: InvoiceDetail["lines"] = [];
  for (const l of answer.seed.lines) {
    const quantity = parseQuantity(String(l.quantity));
    if (quantity === null) return null;
    lines.push({
      description: l.description,
      hsn_sac: l.hsn_sac,
      quantity,
      unit: l.unit,
      rate_paise: l.rate_paise,
      gst_rate_bps: l.gst_rate_bps ?? 0,
      taxable_amount_paise: 0,
      cgst_paise: 0,
      sgst_paise: 0,
      igst_paise: 0,
      line_total_paise: 0,
      service_catalogue_id: l.service_catalogue_id,
      discount_percent_bps: l.discount_percent_bps,
      cess_rate_bps: l.cess_rate_bps,
      cess_specific_paise_per_unit: l.cess_specific_paise_per_unit,
      sales_order_line_id: l.sales_order_line_id,
    });
  }
  return {
    id: "",
    invoice_no: "",
    invoice_date: "",
    due_date: null,
    customer_id: answer.seed.customer_id ?? "",
    supply_state_code: answer.seed.supply_state_code,
    is_interstate: answer.seed.is_interstate,
    notes: null,
    taxable_amount_paise: 0,
    total_gst_paise: 0,
    cgst_paise: 0,
    sgst_paise: 0,
    igst_paise: 0,
    total_paise: 0,
    paid_paise: 0,
    status: "draft",
    journal_entry_id: null,
    issued_at: null,
    created_by_name: null,
    lines,
  };
}
