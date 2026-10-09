/**
 * Invoice workspace navigation — route href builders and the View drawer deep-link
 * (`?invoice=<id>`). Pure string helpers (Batch 2), unit-tested, framework-agnostic.
 */

/** The Sales list (entry point / return target). */
export function salesListHref(clientId: string): string {
  return `/clients/${clientId}/sales`;
}

/** Client home. */
export function clientHref(clientId: string): string {
  return `/clients/${clientId}`;
}

/** Breadcrumbs for an invoice editor page: Client › Sales › <leaf>. */
export function invoiceBreadcrumbs(
  clientId: string,
  clientName: string | undefined,
  leaf: string,
): { label: string; href?: string }[] {
  return [
    { label: clientName || "Client", href: clientHref(clientId) },
    { label: "Sales", href: salesListHref(clientId) },
    { label: leaf },
  ];
}

/** Return to the Sales list with a one-shot flash message (?flash=…) for a toast. */
export function salesListFlashHref(clientId: string, message: string): string {
  return `${salesListHref(clientId)}?flash=${encodeURIComponent(message)}`;
}

/** Edit a draft invoice — or create one, via the "new" id sentinel (the
 * create and edit routes were merged into one to cut the app's redirect
 * rule count; see scripts/generate-redirects.js's budget note). */
export function editInvoiceHref(clientId: string, invoiceId: string): string {
  return `/clients/${clientId}/sales/invoices/${invoiceId}/edit`;
}

/** Create a new invoice. */
export function newInvoiceHref(clientId: string): string {
  return editInvoiceHref(clientId, "new");
}

/** Read the `?invoice=<id>` deep-link param from a location search string. */
export function parseInvoiceParam(search: string): string | null {
  const v = new URLSearchParams(search).get("invoice");
  return v && v.trim() ? v : null;
}

/**
 * Build a `pathname?query` string with the `invoice` deep-link param set (open the
 * drawer) or removed (close it), preserving every other query param. Returns just the
 * pathname when no params remain.
 */
export function withInvoiceParam(pathname: string, search: string, invoiceId: string | null): string {
  const p = new URLSearchParams(search);
  if (invoiceId) p.set("invoice", invoiceId);
  else p.delete("invoice");
  const qs = p.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

/**
 * The tabs of a client's Sales screen that a PRACTICE screen may deep-link to.
 * Every id here must be one of that screen's own TABS (the screen validates
 * `?tab=` against them and falls back to the invoice list for anything else);
 * `scripts/the-practice-fee-screens-link-to-the-practice-invoices.test.ts`
 * reads the Sales page and fails an id it does not hold, so a renamed tab
 * cannot turn a link into a silent landing on the wrong one. "Invoices" is the
 * default and is deliberately not listed: a bare URL opens it.
 */
export const PRACTICE_SALES_TAB_IDS = ["receipts"] as const;
export type PracticeSalesTab = (typeof PRACTICE_SALES_TAB_IDS)[number];

/**
 * Where the practice's OWN fee invoices live (PRE-A-018). The fee schedules
 * (/practice/billing) and the ageing (/practice/ar) are firm-level screens that
 * generate and age invoices, but an invoice is confirmed, issued and paid in
 * the sales workspace of the practice's internal client — the same screen any
 * client's invoices are issued from. This builds the href into it.
 *
 * `internalClientId` is whatever the server said (`GET /api/practice` or
 * `GET /api/billing/service-options`), typed `unknown` on purpose: this
 * FAILS CLOSED, returning null for a missing, non-string, blank or
 * `_placeholder` id, so a screen that has not resolved the practice yet (or
 * whose lookup failed) renders no link rather than `/clients//sales`.
 *
 * `target.tab` opens one of PRACTICE_SALES_TAB_IDS (receipts is where a
 * payment with the TDS the customer withheld is recorded); `target.invoiceId`
 * opens that invoice's drawer on the Invoices tab (`?invoice=`, which fetches
 * the invoice by id, so it opens whatever the period filter says). A tab wins
 * over an invoice id, because the drawer belongs to the Invoices tab.
 *
 * This only builds a string. Whether the caller may open the destination is the
 * destination's own permission (the practice client is Partner-only), and the
 * callers are PartnerGuard-ed pages.
 */
export function practiceSalesHref(
  internalClientId: unknown,
  target: { tab?: PracticeSalesTab; invoiceId?: string | null } = {},
): string | null {
  if (typeof internalClientId !== "string") return null;
  const id = internalClientId.trim();
  if (!id || id === "_placeholder") return null;
  const base = salesListHref(encodeURIComponent(id));
  if (target.tab && (PRACTICE_SALES_TAB_IDS as readonly string[]).includes(target.tab)) {
    return `${base}?tab=${encodeURIComponent(target.tab)}`;
  }
  const invoiceId = typeof target.invoiceId === "string" ? target.invoiceId.trim() : "";
  return invoiceId ? withInvoiceParam(base, "", invoiceId) : base;
}
