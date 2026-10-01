/**
 * How FORM GST ITC-04 and a lot coming back from a job worker are WORDED and
 * KEYED (GST-30).
 *
 * THIS DECIDES NOTHING. Which challans are on the form, which window carries
 * them, what is still with the job worker and which s.143 date it is running
 * towards are `domain/gst/itc_04.py`'s answers, carried on the statement. What
 * lives here is only:
 *
 *   * the sentence for a clock's state, from the server's own `overdue`,
 *     `days_remaining` and `due_back_by` — nothing here counts a day;
 *   * turning a CA's typed lot into the request body, through
 *     `lib/money/rupeeInput.parseQuantity` — a quantity is NUMERIC(10,3) and
 *     `parseFloat("12abc")` is 12 — refusing what is not a quantity rather than
 *     sending `null` or `NaN`.
 *
 * Two rules worth a test, because each reads like a convenience and is not:
 *
 *   * AN UNRUN CLOCK IS NOT A SAFE ONE. Goods whose kind (inputs or capital
 *     goods) was never recorded have no date to show, and the periods differ by
 *     a factor of three. They read "cannot be run", never "no deadline".
 *   * A LOT IS NOT THE WHOLE CHALLAN. Returning part of a line moves nothing
 *     about the day the goods left; the wording says what is LEFT.
 */
import type { ChallanReturnBody, DeemedSupplyClock } from "@/lib/api";
import { parseQuantity } from "../money/rupeeInput.ts";

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** The clock for what is still outstanding, in one line. */
export function clockText(c: DeemedSupplyClock): string {
  if (!c.applies) {
    // Moulds, dies, jigs, fixtures and tools: outside both periods. The server's
    // own sentence says why.
    return c.consequence || "No s.143 period runs on these goods.";
  }
  if (!c.due_back_by) {
    return "The period cannot be run — "
      + (c.gaps[0] ?? "the challan carries no date or kind of goods.");
  }
  if (c.overdue === true) {
    const n = Math.abs(c.days_remaining ?? 0);
    return `Past the date — due back by ${c.due_back_by}`
      + (c.days_remaining != null ? ` (${n} ${plural(n, "day", "days")} ago)` : "");
  }
  const n = c.days_remaining ?? 0;
  return `${n} ${plural(n, "day", "days")} left — due back by ${c.due_back_by}`;
}

/** Only a lapsed clock is a problem; one that cannot be run is attention,
 *  because nobody can say it is fine. */
export function clockTone(c: DeemedSupplyClock): "problem" | "attention" | "neutral" {
  if (!c.applies) return "neutral";
  if (c.overdue === true) return "problem";
  if (!c.due_back_by) return "attention";
  return "neutral";
}

export interface LotForm {
  returned_on: string;
  returned: string;
  wasted: string;
  job_worker_challan_no: string;
  job_worker_challan_date: string;
  nature_of_job_work: string;
}

export const BLANK_LOT: LotForm = {
  returned_on: "", returned: "", wasted: "", job_worker_challan_no: "",
  job_worker_challan_date: "", nature_of_job_work: "",
};

export type LotResult =
  | { ok: true; body: ChallanReturnBody }
  | { ok: false; error: string };

/** A typed lot as a request body, or the sentence saying why it is not one.
 *  Blank quantities are nil — a lot may be waste alone, or goods alone — but a
 *  quantity that is not a quantity is refused, never coerced. */
export function lotBody(clientId: string, challanLineId: string, f: LotForm): LotResult {
  if (!f.returned_on) return { ok: false, error: "Give the date the goods came back." };
  const returned = f.returned.trim() === "" ? 0 : parseQuantity(f.returned);
  const wasted = f.wasted.trim() === "" ? 0 : parseQuantity(f.wasted);
  if (returned === null) {
    return { ok: false, error: "The quantity returned is not a quantity (up to three decimals)." };
  }
  if (wasted === null) {
    return { ok: false, error: "The quantity lost or wasted is not a quantity (up to three decimals)." };
  }
  if (returned < 0 || wasted < 0) {
    return { ok: false, error: "A quantity cannot be negative." };
  }
  if (returned === 0 && wasted === 0) {
    return { ok: false, error: "Give the quantity that came back, or the quantity lost or wasted." };
  }
  return {
    ok: true,
    body: {
      client_id: clientId,
      challan_line_id: challanLineId,
      returned_on: f.returned_on,
      quantity_returned: returned,
      quantity_lost_or_wasted: wasted,
      job_worker_challan_no: f.job_worker_challan_no.trim() || null,
      job_worker_challan_date: f.job_worker_challan_date || null,
      nature_of_job_work: f.nature_of_job_work.trim() || null,
    },
  };
}
