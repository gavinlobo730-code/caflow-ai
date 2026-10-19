/**
 * The delivery log of emailed customer statements: what the server sent, in the words a screen shows.
 *
 * `GET /api/customer-statements/deliveries` answers a window (apps/api/core/list_window.py) of the newest rows. This module
 * reads that answer through the one window reader and holds the wording; it decides nothing about a delivery. A row says what
 * the MAIL SERVICE reported: `sent` is "the service accepted the message", not "the customer opened it", and `bounced` is set
 * later by the provider's own event. The screen says so rather than letting "Sent" read as "received".
 */
import { readWindow, type ReadWindow } from "../lists/readWindow.ts";

export interface StatementDelivery {
  id: string;
  period_start: string | null;
  period_end: string | null;
  sent_to: string;
  sent_by_email: string | null;
  status: string;
  error_message: string | null;
  sent_at: string | null;
  created_at: string | null;
}

/** The statuses the table's CHECK allows (migration 354's table), in the words of the invoice delivery log. */
export const STATEMENT_DELIVERY_STATUS_LABEL: Record<string, string> = {
  queued: "Queued", sending: "Sending", sent: "Sent", failed: "Failed", bounced: "Bounced",
};

/** One sentence under the table so "Sent" is not read as "received". */
export const STATEMENT_DELIVERY_NOTE =
  "Sent means the mail service accepted the message. It does not say the customer opened it; Bounced is set when the service later reports the address refused it.";

/**
 * The window from the envelope's `data`, or null when it is neither a window nor a bare list (a refusal, null, a scalar), in
 * which case the screen says the log could not be read, which is a different statement from "nothing has been sent". A row
 * that is not an object is dropped, because it cannot be drawn; a bare list from a server that predates the window is read as
 * complete.
 */
export function readStatementDeliveries(data: unknown, askedLimit: number): ReadWindow<StatementDelivery> | null {
  const window = readWindow<unknown>(data, "deliveries", askedLimit);
  if (!window) return null;
  const rows = window.rows.filter(
    (r): r is StatementDelivery => typeof r === "object" && r !== null && typeof (r as { id?: unknown }).id === "string",
  );
  return { ...window, rows };
}

/** The label for a status, or the status itself when the server knows one this build does not. */
export function deliveryStatusLabel(status: string): string {
  return STATEMENT_DELIVERY_STATUS_LABEL[status] ?? status;
}
