"use client";

/**
 * Hand-off for "Duplicate purchase bill" — the exact pattern of
 * lib/invoices/duplicateSeed.ts (see its doc comment for why sessionStorage,
 * not a query param): the copy is never persisted server-side up front. The
 * full source bill is stashed here, the New Bill route is opened, and
 * PurchaseBillEditor pre-fills its (unsaved) form from it. The vendor
 * invoice number is deliberately NOT copied — each vendor bill has its own
 * number, and pre-filling the old one would invite a silent duplicate; the
 * CA types the new bill's number like any other manual entry.
 */
import type { PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";

const KEY = "practicesync_purchase_bill_duplicate_seed_v1";

export function writePurchaseBillDuplicateSeed(bill: PurchaseBillDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(bill));
  } catch {
    // Private-mode / quota errors: the New Bill page just opens blank.
  }
}

/** Reads and immediately clears the seed, so a later genuinely-blank visit
 * to New Bill never resurrects stale data. */
export function readAndClearPurchaseBillDuplicateSeed(): PurchaseBillDetail | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as PurchaseBillDetail;
  } catch {
    return null;
  }
}
