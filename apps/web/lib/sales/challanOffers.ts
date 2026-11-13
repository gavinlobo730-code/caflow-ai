/**
 * Who a delivery challan's two ITC-04 remedies are offered to (POST-A-431, POST-A-423). Pure, and pinned to the server by `shared/challan-offer-vectors.json`, which `apps/api/tests/` and the web suite both read.
 *
 * These are DISPLAY conditions, not statutory rules: the server judges every write (`update_challan` refuses a back day on a draft or a cancelled challan, a state code that is not one), and the statement's own
 * tests of the same facts are `itc_04.is_received_back_without_a_day` and `itc_04._job_worker`. They live here, in a module with no imports, so a test can evaluate them against the server's answers and a drift
 * between the screen and the statement fails instead of leaving a gap the statement names and no screen offers to close.
 */

export interface ChallanFacts {
  reason?: string | null;
  status: string;
  consignee_gstin?: string | null;
  place_of_supply?: string | null;
  received_back_on?: string | null;
  clock?: { applies?: boolean | null } | null;
}

/** A challan whose back day is not recorded and which the goods have left on: an issued one with a period running (its day stops the clock), and ANY challan recorded as received back with no day, whatever its
 *  period (POST-A-431): tools, moulds, dies, jigs and fixtures run no period, and the box used to skip them, so the FORM GST ITC-04 statement named a challan no screen could give a day. */
export const owesItsBackDay = (c: ChallanFacts): boolean =>
  !c.received_back_on && ((c.status === "issued" && c.clock?.applies === true) || c.status === "received_back");

/** A job-work challan, not cancelled, whose job worker has no GSTIN recorded: the State the goods went to is what FORM GST ITC-04 reads for them, so it is the box to offer (empty, or holding the State
 *  already recorded so a wrong pick can be changed). A challan WITH a GSTIN reads its State from the GSTIN and is not offered it. */
export const jobWorkerHasNoGstin = (c: ChallanFacts): boolean =>
  c.reason === "job_work" && c.status !== "cancelled" && !(c.consignee_gstin ?? "").trim();
