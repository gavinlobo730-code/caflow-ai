/**
 * Which GSTR-3B a Rule 37 reversal belongs in.
 *
 * Rule 37(1) does not say "reverse it when you notice". It puts each reversal
 * in ONE return: the period immediately following the one in which the 180
 * days expired. So the 3B screen cannot just show every overdue bill — it has
 * to say which of them this return has to carry, and which belonged to a
 * return that has already been filed.
 *
 * The backend decides the period (services/itc_reversal_service.rule37_report
 * returns reverse_in_period per bill); this module only sorts the answer into
 * the two buckets the screen shows. Kept out of lib/data/gst.ts, which pulls in
 * the Supabase client and cannot be imported by a bare node test.
 */

/** A Rule 37 finding, narrowed to what the split needs. */
export interface PeriodedBill {
  /** MMYYYY, from the API. */
  reverse_in_period: string;
}

/**
 * MMYYYY as a sortable YYYYMM key.
 *
 * MMYYYY does not sort chronologically as a string: "012026" (January 2026)
 * compares BELOW "122025" (December 2025), so a plain `<` would file a January
 * reversal as belonging to an earlier period than the December before it and
 * quietly move it out of the return that has to carry it.
 */
export function chronoKey(mmyyyy: string): string {
  return mmyyyy.slice(2) + mmyyyy.slice(0, 2);
}

export interface Rule37Split<T> {
  /** Bills whose reversal Rule 37(1) puts in THIS return. */
  due: T[];
  /** Bills whose reversal belonged to an earlier return. */
  earlier: T[];
}

/**
 * Split findings into "this return" and "an earlier one".
 *
 * A bill dated to a LATER period is in neither bucket. The report is asked as
 * at the period end, so that should not happen — but if it ever does, showing
 * a future reversal as due now would have the CA reverse credit early, and
 * silently dropping it is the safer of the two wrong answers.
 */
export function splitRule37Bills<T extends PeriodedBill>(
  bills: readonly T[],
  period: string,          // MMYYYY, the return being prepared
): Rule37Split<T> {
  const here = chronoKey(period);
  return {
    due: bills.filter(b => chronoKey(b.reverse_in_period) === here),
    earlier: bills.filter(b => chronoKey(b.reverse_in_period) < here),
  };
}

/**
 * Last calendar day of a YYYY-MM month, as YYYY-MM-DD.
 *
 * This is what the Rule 37 report is asked `as_of`. Not today: the CA is
 * preparing one specific return, and a bill that crosses 180 days next week
 * belongs in next month's answer.
 *
 * Built in UTC. A local-time Date on a machine behind UTC rolls the last
 * instant of the month back into the previous day, which would ask the
 * question one day early every single month.
 */
export function periodEndDate(yearMonth: string): string {
  const [y, m] = yearMonth.split("-").map(Number);
  // Day 0 of the NEXT month is the last day of this one, leap years included.
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}
