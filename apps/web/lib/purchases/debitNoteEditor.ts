/**
 * Pure Purchase-Debit-Note editor domain primitives — types, GST preview
 * totals, and validation. Mirrors lib/purchases/billEditor.ts's shape; GST
 * math reuses dnLineGst directly (a debit note line IS dnLineGst's native
 * input shape, no adapter needed) so this preview never drifts from what
 * routers/debit_notes.py actually posts.
 *
 * No §17(5) blocked-credit heuristic here (unlike billEditor.ts) — a debit
 * note reduces ITC already claimed on the linked bill, it doesn't claim new
 * ITC, so the warning wouldn't mean the same thing here.
 */
import { dnLineGst } from "./debitNoteGst.ts";

export interface DebitNoteEditorLine {
  description: string;
  hsn_sac: string;
  qty: string; // string-typed input, parsed on use
  rate: string; // rupees
  gst_rate: number; // percent, e.g. 18
  unit: string;
  service_catalogue_id: string;
}

/** A line is "valid" (postable) when it has positive qty & rate and a linked
 * Product/Service. Description is deliberately NOT required — same rule as
 * bill/invoice lines. */
export function isValidDebitNoteLine(l: DebitNoteEditorLine): boolean {
  return (parseFloat(l.qty) || 0) > 0 && (parseFloat(l.rate) || 0) > 0 && !!l.service_catalogue_id;
}

export interface DebitNotePreviewTotals {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  gst_paise: number;
  grand_total_paise: number;
}

export function previewDebitNoteTotals(lines: DebitNoteEditorLine[], isInterstate: boolean): DebitNotePreviewTotals {
  let taxable = 0, cgst = 0, sgst = 0, igst = 0;
  for (const l of lines) {
    if (!isValidDebitNoteLine(l)) continue;
    const g = dnLineGst(
      { quantity: parseFloat(l.qty) || 0, rate: parseFloat(l.rate) || 0, gst_rate_bps: Math.round(l.gst_rate * 100) },
      isInterstate,
    );
    taxable += g.taxable_paise; cgst += g.cgst_paise; sgst += g.sgst_paise; igst += g.igst_paise;
  }
  const gst_paise = cgst + sgst + igst;
  return { taxable_paise: taxable, cgst_paise: cgst, sgst_paise: sgst, igst_paise: igst, gst_paise, grand_total_paise: taxable + gst_paise };
}

// ── Editor validation ────────────────────────────────────────────────────────
// Mirrors the minimums the backend enforces so the UI can block + explain
// BEFORE calling the API. The server remains authoritative — including the
// "exceeds bill outstanding" check, which only applies at ISSUE time
// (routers/debit_notes.py's issue_debit_note), not at save-draft time.
export interface DebitNoteEditorValidationInput {
  vendorId: string;
  debitNoteDate: string;
  lines: DebitNoteEditorLine[];
}

export interface DebitNoteEditorValidation {
  errors: {
    vendor?: string;
    debitNoteDate?: string;
    lines?: string;
  };
  ok: boolean;
}

export function validateDebitNoteEditor(input: DebitNoteEditorValidationInput): DebitNoteEditorValidation {
  const errors: DebitNoteEditorValidation["errors"] = {};
  if (!input.vendorId) errors.vendor = "Select a vendor.";
  if (!input.debitNoteDate) errors.debitNoteDate = "Debit note date is required.";
  if (input.lines.filter(isValidDebitNoteLine).length === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}
