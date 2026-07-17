/**
 * Pure Sales-Debit-Note editor domain primitives — validation only. The GST
 * preview totals reuse lib/invoices/gst.ts's previewTotals/computeGst
 * directly (no separate math here): sales_debit_notes.py's
 * _compute_line_gst is the same "full tax first, then split" rule as
 * sales_invoices.py, and InvoiceLine is already the right shape (qty/rate/
 * gst_rate as a percentage, serviceCatalogueId). Unlike a Sales Invoice,
 * a debit note's total_paise is NOT rupee-rounded by the backend — callers
 * must pass applyRoundOff=false to previewTotals.
 */
import { isValidLine, type InvoiceLine } from "../invoices/gst.ts";

export interface SalesDebitNoteEditorValidationInput {
  customerId: string;
  debitNoteDate: string;
  lines: InvoiceLine[];
}

export interface SalesDebitNoteEditorValidation {
  errors: {
    customer?: string;
    debitNoteDate?: string;
    lines?: string;
  };
  ok: boolean;
}

export function validateSalesDebitNoteEditor(input: SalesDebitNoteEditorValidationInput): SalesDebitNoteEditorValidation {
  const errors: SalesDebitNoteEditorValidation["errors"] = {};
  if (!input.customerId) errors.customer = "Select a customer.";
  if (!input.debitNoteDate) errors.debitNoteDate = "Debit note date is required.";
  if (input.lines.filter(isValidLine).length === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}
