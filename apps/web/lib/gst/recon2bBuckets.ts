/**
 * The four answers a GSTR-2B reconciliation gives, and the words the screen uses
 * for them (PRE-A-001).
 *
 * The statuses are the SERVER's (`domain/gst/itc_matching`: `matched`,
 * `amount_mismatch`, `missing_in_2b`, `missing_in_books`) and this module decides
 * none of them. It holds what the screen SAYS about each, in one place, because
 * the same four words reached a CA in two forms on one screen: the bucket
 * buttons said "Supplier has not filed" and the line under the file chooser —
 * "Last reconciled for this period" — printed the raw token
 * `missing_in_books: 3`. The two come from this map now.
 *
 * `apps/api/tests/test_the_2b_screen_names_what_it_shows.py` holds the statuses
 * here equal to the ones `reconcile` can produce, from the Python side (a guard
 * written in apps/web would assert this file against a copy of itself).
 */

export interface Recon2BBucket {
  /** The server's status word. */
  status: string;
  label: string;
  hint: string;
  tone: string;
}

export const RECON_2B_BUCKETS: Recon2BBucket[] = [
  { status: "matched", label: "Matched", tone: "text-state-ready",
    hint: "The bill and the 2B document agree, to the paisa." },
  { status: "amount_mismatch", label: "Amount mismatch", tone: "text-state-attention",
    hint: "Both exist and the tax differs — one of the two documents is wrong." },
  { status: "missing_in_2b", label: "Supplier has not filed", tone: "text-state-problem",
    hint: "We hold the bill; §16(2)(aa) makes the credit unavailable until the supplier files. Chase the SUPPLIER." },
  { status: "missing_in_books", label: "No bill in the books", tone: "text-blue-700",
    hint: "The supplier filed it and we have no bill — credit that may be available and is not being claimed. Chase the DOCUMENT." },
];

/**
 * The label for a status. A status this map does not know (the server gained a
 * fifth) is shown as its own words, underscores taken out, rather than hidden:
 * a count with no name beside it would read as a smaller reconciliation.
 */
export function reconStatusLabel(status: string): string {
  const known = RECON_2B_BUCKETS.find((b) => b.status === status);
  if (known) return known.label;
  const words = String(status ?? "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unclassified";
}

/**
 * "Amount mismatch 1 · No bill in the books 3" for the saved reconciliation, in
 * the screen's own order and with its own words, never the raw tokens. A status
 * with a zero or non-numeric count is left out.
 */
export function savedReconciliationBreakdown(byStatus: Record<string, number> | null | undefined): string {
  const counts = byStatus && typeof byStatus === "object" ? byStatus : {};
  const known = RECON_2B_BUCKETS.map((b) => b.status);
  const order = [...known, ...Object.keys(counts).filter((s) => !known.includes(s)).sort()];
  return order
    .filter((s) => Number.isFinite(counts[s]) && counts[s] > 0)
    .map((s) => `${reconStatusLabel(s)} ${counts[s]}`)
    .join(" · ");
}

/** How a supplier is named in a row: the name the file (or the vendor record)
 *  gives with the GSTIN under it, or the GSTIN once where there is no name. */
export function supplierLines(
  name: string | null | undefined, gstin: string | null | undefined,
): { primary: string; secondary: string | null } {
  const n = (name ?? "").trim();
  const g = (gstin ?? "").trim();
  if (n) return { primary: n, secondary: g && g !== n ? g : null };
  return { primary: g || "—", secondary: null };
}
