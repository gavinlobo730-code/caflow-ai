"use client";

/**
 * Hand-off for "Duplicate purchase credit note" — same sessionStorage
 * pattern as lib/purchases/debitNoteDuplicateSeed.ts. purchase_bill_id is
 * deliberately NOT copied — a fresh note has no reason to default to the
 * same bill.
 */
import type { PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";

const KEY = "practicesync_purchase_credit_note_duplicate_seed_v1";

export function writePurchaseCreditNoteDuplicateSeed(note: PurchaseCreditNoteDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(note));
  } catch {
    // Private-mode / quota errors: the New Credit Note page just opens blank.
  }
}

export function readAndClearPurchaseCreditNoteDuplicateSeed(): PurchaseCreditNoteDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as PurchaseCreditNoteDetail;
  } catch {
    return null;
  }
}
