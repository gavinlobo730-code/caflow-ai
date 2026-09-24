/**
 * Is this bank line still waiting on a human to decide the withholding?
 *
 * D19, migration 413. A rule the CA marked `flags_tds_decision` stamps
 * `tds_decision_needed` on every line it passes — and a trusted rule passes
 * with nobody watching, so the flag is the only trace that a withholding
 * question was left open on a line that is already in the books.
 *
 * PENDING IS TWO COLUMNS, NOT ONE, and that is deliberate. `tds_decision_needed`
 * is never cleared; resolution writes `tds_decision_resolved_at`. Three states,
 * not two — never flagged, flagged and waiting, flagged and dealt with — because
 * the third is the audit answer to "did anyone look at the withholding on this
 * line", which is the question a s.201 proceeding asks. Clearing the boolean
 * would lose it.
 *
 * The same predicate is migration 413's partial index
 * (`WHERE tds_decision_needed AND tds_decision_resolved_at IS NULL`). It is a
 * two-column test rather than a statutory rule, so it is written here as well
 * as there; nothing about a rate, a section or an amount is decided in the
 * browser, and nothing here is.
 *
 * AN ABSENT KEY READS AS NOT PENDING, which is the safe direction for a
 * frontend deployed ahead of its backend: a chip that fails to appear is a
 * missing prompt, while one that appears on every line trains the CA to ignore
 * it — and an ignored prompt is worse than none.
 */
export interface TdsDecisionFields {
  tds_decision_needed?: boolean | null;
  tds_decision_resolved_at?: string | null;
}

export function tdsDecisionPending(row: TdsDecisionFields): boolean {
  return Boolean(row.tds_decision_needed) && !row.tds_decision_resolved_at;
}
