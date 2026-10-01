/**
 * What the browser needs to ASK for a server-made report file, and nothing the
 * server decides (accounting-16).
 *
 * The PDF and the spreadsheet are built in `apps/api` from the very report the
 * screen is showing (`services/report_export_service.py`), so the figures, the
 * letterhead, the page furniture and the refusal rules are all the server's.
 * What lives here is the two small things a button cannot do without: how a
 * request is spelled, and how a refusal is read.
 *
 * There is deliberately NO list in this file of which format each report
 * offers. The screen that places a button says which it offers, and the server
 * REFUSES the rest in words — a second list here would be a place for the two
 * to disagree.
 */

export type ExportReport =
  | "ledger"
  | "trial-balance"
  | "cash-flow"
  | "ar-ageing"
  | "ap-ageing";

export type ExportFormat = "pdf" | "xlsx";

/** The parameters the screen's own report takes, by their API names. An absent
 *  or empty one is left off, so the server applies the same default the screen
 *  gets. */
export type ExportParams = Partial<
  Record<"account_id" | "start_date" | "end_date" | "as_of_date" | "as_of" | "basis", string>
>;

/** The query string for one export. `client_id` is always sent — a report file
 *  is headed by whose books it is, and the server refuses one without. */
export function exportQuery(
  clientId: string,
  format: ExportFormat,
  params: ExportParams = {},
): string {
  const q = new URLSearchParams({ client_id: clientId, format });
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" && value.trim() !== "") q.set(key, value);
  }
  return q.toString();
}

/**
 * The sentence to show for a failed download.
 *
 * `downloadFile` throws `API error 422: {"detail":"…"}` because a file
 * response has no envelope to read. The server's refusals are written for a CA
 * ("This ledger has 9,999 lines in the period, and an export is limited to
 * 6,000. Choose a shorter period…") and showing the JSON around them would hide
 * the one part that says what to do.
 */
export function exportErrorMessage(e: unknown): string {
  const raw = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  const m = raw.match(/^API error (\d{3}):\s*([\s\S]*)$/);
  if (m) {
    try {
      const body = JSON.parse(m[2]);
      if (body && typeof body.detail === "string" && body.detail.trim()) return body.detail;
      if (body && typeof body.error === "string" && body.error.trim()) return body.error;
    } catch {
      /* not JSON — fall through to the status wording */
    }
    return `The export could not be made (error ${m[1]}).`;
  }
  return raw || "The export could not be made.";
}
