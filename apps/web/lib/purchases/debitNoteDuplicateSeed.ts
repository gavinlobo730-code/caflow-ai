"use client";

/**
 * Hand-off for "Duplicate debit note" — same sessionStorage pattern as
 * lib/purchases/duplicateSeed.ts (see its doc comment for why sessionStorage,
 * not a query param): nothing is created server-side up front. The source
 * note is stashed here, the New Debit Note route is opened, and
 * DebitNoteEditor pre-fills its (unsaved) form from it. purchase_bill_id is
 * deliberately NOT copied — a return against one bill has no reason to
 * default to the same bill on a fresh note.
 */
import type { DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";

const KEY = "practicesync_debit_note_duplicate_seed_v1";

export function writeDebitNoteDuplicateSeed(note: DebitNoteDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(note));
  } catch {
    // Private-mode / quota errors: the New Debit Note page just opens blank.
  }
}

/** Reads and immediately clears the seed, so a later genuinely-blank visit
 * to New Debit Note never resurrects stale data. */
export function readAndClearDebitNoteDuplicateSeed(): DebitNoteDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as DebitNoteDetail;
  } catch {
    return null;
  }
}
