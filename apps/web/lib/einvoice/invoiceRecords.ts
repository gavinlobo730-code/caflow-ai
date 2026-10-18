/**
 * Finding an invoice's own e-invoice and e-way bill records (POST-A-263).
 *
 * The invoice drawer used to read every record a client had ever had and look for its invoice among them. The two list routes
 * take `sales_invoice_id` now and answer a WINDOW (`{records, returned, has_more, limit, max_limit}`, apps/api/core/list_window.py),
 * so the drawer asks for its own invoice's and reads the answer through `readWindow`. This module holds the URL, so the screen
 * and the drawer cannot build it two ways, and the one sentence said when a read did not come back whole: an empty panel next
 * to a failed read would offer to prepare a record the invoice may already have (the server refuses a second live e-invoice
 * record, but the CA should not have to find that out by being refused).
 */
import type { ReadWindow } from "../lists/readWindow.ts";

export type RecordKind = "einvoice" | "eway-bill";

/** Each path spelled whole, so a scan for the routes the browser names (apps/api/tests/test_every_api_path_the_browser_calls_exists.py)
 *  can check that both are served; a path built from the kind could not be read. */
const RECORDS_PATH: Record<RecordKind, string> = {
  "einvoice": "/api/einvoice/records",
  "eway-bill": "/api/eway-bill/records",
};

/** One invoice has a handful of records, so the drawer's window is the server's default and never has to grow. */
export const INVOICE_RECORDS_WINDOW = 100;

export function recordsUrl(
  kind: RecordKind,
  clientId: string,
  opts: { salesInvoiceId?: string; limit?: number } = {},
): string {
  const q = new URLSearchParams({ client_id: clientId });
  if (opts.salesInvoiceId) q.set("sales_invoice_id", opts.salesInvoiceId);
  if (opts.limit !== undefined) q.set("limit", String(opts.limit));
  return `${RECORDS_PATH[kind]}?${q.toString()}`;
}

/**
 * What the drawer says when the two reads did not both come back whole, or null when they did.
 * `null` for a read means it failed or was not a window; `hasMore` means the invoice has more records than the window held.
 */
export function recordsReadNote(
  einvoice: ReadWindow<unknown> | null,
  eway: ReadWindow<unknown> | null,
): string | null {
  const failed: string[] = [];
  if (!einvoice) failed.push("e-invoice");
  if (!eway) failed.push("e-way bill");
  if (failed.length > 0) {
    return `This invoice's ${failed.join(" and ")} records could not be read, so the panel below may be missing some. ` +
      "Close and reopen the invoice to try again.";
  }
  if (einvoice?.hasMore || eway?.hasMore) {
    return "This invoice has more e-invoice or e-way bill records than the panel below shows.";
  }
  return null;
}
