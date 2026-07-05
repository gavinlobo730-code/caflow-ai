/**
 * Invoice workspace navigation — route href builders and the View drawer deep-link
 * (`?invoice=<id>`). Pure string helpers (Batch 2), unit-tested, framework-agnostic.
 */

/** The Sales list (entry point / return target). */
export function salesListHref(clientId: string): string {
  return `/clients/${clientId}/sales`;
}

/** Create a new invoice. */
export function newInvoiceHref(clientId: string): string {
  return `/clients/${clientId}/sales/invoices/new`;
}

/** Edit a draft invoice. */
export function editInvoiceHref(clientId: string, invoiceId: string): string {
  return `/clients/${clientId}/sales/invoices/${invoiceId}/edit`;
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
