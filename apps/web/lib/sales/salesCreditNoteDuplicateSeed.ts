"use client";

/**
 * Hand-off for "Duplicate credit note" — same sessionStorage pattern as
 * lib/sales/salesDebitNoteDuplicateSeed.ts (see its doc comment for why
 * sessionStorage, not a query param). Nothing is created server-side up
 * front. The source note is stashed here, the New Credit Note route is
 * opened, and SalesCreditNoteEditor pre-fills its (unsaved) form from it.
 * sales_invoice_id is deliberately NOT copied — a return against one
 * invoice has no reason to default to the same invoice on a fresh note.
 */
import type { SalesCreditNoteDetail } from "@/components/sales/SalesCreditNoteEditor";

const KEY = "practicesync_sales_credit_note_duplicate_seed_v1";

export function writeSalesCreditNoteDuplicateSeed(note: SalesCreditNoteDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(note));
  } catch {
    // Private-mode / quota errors: the New Credit Note page just opens blank.
  }
}

/** Reads and immediately clears the seed, so a later genuinely-blank visit
 * to New Credit Note never resurrects stale data. */
export function readAndClearSalesCreditNoteDuplicateSeed(): SalesCreditNoteDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as SalesCreditNoteDetail;
  } catch {
    return null;
  }
}
