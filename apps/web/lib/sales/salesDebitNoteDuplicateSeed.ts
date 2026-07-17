"use client";

/**
 * Hand-off for "Duplicate debit note" — same sessionStorage pattern as
 * lib/purchases/debitNoteDuplicateSeed.ts (see its doc comment for why
 * sessionStorage, not a query param). Nothing is created server-side up
 * front. The source note is stashed here, the New Debit Note route is
 * opened, and SalesDebitNoteEditor pre-fills its (unsaved) form from it.
 * sales_invoice_id is deliberately NOT copied — a correction against one
 * invoice has no reason to default to the same invoice on a fresh note.
 */
import type { SalesDebitNoteDetail } from "@/components/sales/SalesDebitNoteEditor";

const KEY = "practicesync_sales_debit_note_duplicate_seed_v1";

export function writeSalesDebitNoteDuplicateSeed(note: SalesDebitNoteDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(note));
  } catch {
    // Private-mode / quota errors: the New Debit Note page just opens blank.
  }
}

/** Reads and immediately clears the seed, so a later genuinely-blank visit
 * to New Debit Note never resurrects stale data. */
export function readAndClearSalesDebitNoteDuplicateSeed(): SalesDebitNoteDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as SalesDebitNoteDetail;
  } catch {
    return null;
  }
}
