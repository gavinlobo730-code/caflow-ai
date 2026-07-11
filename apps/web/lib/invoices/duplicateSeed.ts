"use client";

/**
 * Hand-off for "Duplicate invoice" — QuickBooks-style: the copy is never
 * persisted server-side up front. Instead the full source invoice is stashed
 * here, the New Invoice route is opened, and InvoiceEditor pre-fills its
 * (unsaved) form from it. The CA reviews/edits like any other new invoice —
 * types their own invoice number, sees the SAME inline "already exists"
 * error as any manually-typed collision if they forget to change it — and
 * nothing is created until they actually save.
 *
 * sessionStorage (not a query param) because the seed is a full invoice
 * with an arbitrary number of lines, and because this codebase's own
 * static-export/_placeholder routing quirk (see ClientNavContext.tsx) makes
 * URL-param state on this route fragile; a one-shot read-and-clear on mount
 * sidesteps both.
 */
import type { InvoiceDetail } from "@/lib/invoices/shared";

const KEY = "practicesync_invoice_duplicate_seed_v1";

export function writeDuplicateSeed(inv: InvoiceDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(inv));
  } catch {
    // Private-mode / quota errors: the New Invoice page just opens blank.
  }
}

/** Reads and immediately clears the seed, so a later genuinely-blank visit
 * to New Invoice (browser back, then New Invoice from the toolbar) never
 * resurrects stale data. */
export function readAndClearDuplicateSeed(): InvoiceDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as InvoiceDetail;
  } catch {
    return null;
  }
}
