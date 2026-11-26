/**
 * A client's customer list (Sales > Customers) and supplier list (Purchases > Vendors) on the shared read cache (POST-A-124).
 *
 * Both are lists a person returns to on every tab switch. The last answer is painted at once and the real read ALWAYS follows; the screen
 * says when the painted list was read. Only the two list TABS read through here: every picker, every editor and everything that feeds a
 * write keeps reading the table itself, never this cache.
 *
 * Every browser writer of a customer or a supplier forgets its family (`forgetCustomerLists`, `forgetVendorLists`), and the guard
 * `scripts/the-read-cache-is-opt-in-and-never-feeds-a-write.test.ts` finds those writers by RULE (a write to the table or its API) and fails
 * one that does not. A write made somewhere else (the server's Tally import, another person) is caught by the real read that always follows.
 */
import { forgetReads, readKey, readStale } from "../cache/readCache.ts";

export const CUSTOMER_LISTS = "customers";
export const VENDOR_LISTS = "vendors";

/** The client's customer list: `onStale` paints the last answer at once, the promise is the real read (`fetcher`, which throws on a failure). */
export function readCustomerList<T>(clientId: string, fetcher: () => Promise<T[]>, onStale: (rows: T[], readAt: number) => void): Promise<T[]> {
  return readStale(readKey([CUSTOMER_LISTS, clientId]), fetcher, onStale);
}

/** The client's supplier list, the same way. */
export function readVendorList<T>(clientId: string, fetcher: () => Promise<T[]>, onStale: (rows: T[], readAt: number) => void): Promise<T[]> {
  return readStale(readKey([VENDOR_LISTS, clientId]), fetcher, onStale);
}

/** Called by every write of a customer: the cached lists of every client are forgotten (a write names its client, but the cost of
 *  forgetting the others is one fresh read, and a wrong client id would cost a stale list). */
export function forgetCustomerLists(): void {
  forgetReads(CUSTOMER_LISTS);
}

/** Called by every write of a supplier. */
export function forgetVendorLists(): void {
  forgetReads(VENDOR_LISTS);
}
