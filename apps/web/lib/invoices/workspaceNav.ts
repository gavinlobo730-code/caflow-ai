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
