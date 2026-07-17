/**
 * Pure Purchase-Credit-Note editor domain primitives — types, GST preview
 * totals, and validation. Structural mirror of lib/purchases/
 * debitNoteEditor.ts (the increase-side, CGST Act §34(3): a vendor
 * undercharged us, we now owe more) — same GST math, no ceiling to preview
 * (unlike a debit note, a credit note has nothing to exceed).
 */
import { dnLineGst } from "./debitNoteGst.ts";

export interface PurchaseCreditNoteEditorLine {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // rupees
  gst_rate: number; // percent, e.g. 18
  unit: string;
  service_catalogue_id: string;
}

export function isValidPurchaseCreditNoteLine(l: PurchaseCreditNoteEditorLine): boolean {
  return (parseFloat(l.qty) || 0) > 0 && (parseFloat(l.rate) || 0) > 0 && !!l.service_catalogue_id;
}

export interface PurchaseCreditNotePreviewTotals {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  gst_paise: number;
  grand_total_paise: number;
}

export function previewPurchaseCreditNoteTotals(lines: PurchaseCreditNoteEditorLine[], isInterstate: boolean): PurchaseCreditNotePreviewTotals {
  let taxable = 0, cgst = 0, sgst = 0, igst = 0;
  for (const l of lines) {
    if (!isValidPurchaseCreditNoteLine(l)) continue;
    const g = dnLineGst(
      { quantity: parseFloat(l.qty) || 0, rate: parseFloat(l.rate) || 0, gst_rate_bps: Math.round(l.gst_rate * 100) },
      isInterstate,
    );
    taxable += g.taxable_paise; cgst += g.cgst_paise; sgst += g.sgst_paise; igst += g.igst_paise;
  }
  const gst_paise = cgst + sgst + igst;
  return { taxable_paise: taxable, cgst_paise: cgst, sgst_paise: sgst, igst_paise: igst, gst_paise, grand_total_paise: taxable + gst_paise };
}

export interface PurchaseCreditNoteEditorValidationInput {
  vendorId: string;
  creditNoteDate: string;
  lines: PurchaseCreditNoteEditorLine[];
}

export interface PurchaseCreditNoteEditorValidation {
  errors: {
    vendor?: string;
    creditNoteDate?: string;
    lines?: string;
  };
  ok: boolean;
}

export function validatePurchaseCreditNoteEditor(input: PurchaseCreditNoteEditorValidationInput): PurchaseCreditNoteEditorValidation {
  const errors: PurchaseCreditNoteEditorValidation["errors"] = {};
  if (!input.vendorId) errors.vendor = "Select a vendor.";
  if (!input.creditNoteDate) errors.creditNoteDate = "Credit note date is required.";
  if (input.lines.filter(isValidPurchaseCreditNoteLine).length === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}
