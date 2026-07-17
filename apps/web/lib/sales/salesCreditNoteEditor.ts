/**
 * Pure Sales-Credit-Note editor domain primitives — validation only.
 * Structural mirror of lib/sales/salesDebitNoteEditor.ts (the decrease-side,
 * CGST Act §34: a sale is returned/overcharged, the customer owes less) —
 * reuses lib/invoices/gst.ts's previewTotals/computeGst directly, no
 * separate GST math: credit_notes.py's _compute_line_gst is the same "full
 * tax first, then split" rule as sales_invoices.py. Unlike a Sales Invoice,
 * a credit note's total_paise is NOT rupee-rounded by the backend — callers
 * must pass applyRoundOff=false to previewTotals. No outstanding-ceiling
 * concept here (unlike a debit note, a credit note has nothing to preview
 * exceeding at the line level — the ceiling check is server-side on issue).
 */
import { isValidLine, type InvoiceLine } from "../invoices/gst.ts";

export interface SalesCreditNoteEditorValidationInput {
  customerId: string;
  creditNoteDate: string;
  lines: InvoiceLine[];
}

export interface SalesCreditNoteEditorValidation {
  errors: {
    customer?: string;
    creditNoteDate?: string;
    lines?: string;
  };
  ok: boolean;
}

export function validateSalesCreditNoteEditor(input: SalesCreditNoteEditorValidationInput): SalesCreditNoteEditorValidation {
  const errors: SalesCreditNoteEditorValidation["errors"] = {};
  if (!input.customerId) errors.customer = "Select a customer.";
  if (!input.creditNoteDate) errors.creditNoteDate = "Credit note date is required.";
  if (input.lines.filter(isValidLine).length === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}
