/**
 * `public.tax_audits` is `UNIQUE(client_id, financial_year)` (migration 035).
 * The Add Audit form defaults to the current financial year and (when opened
 * from a client's own workspace) that client — exactly the pair that already
 * has a row the moment the firm has tracked one audit for the year — so a
 * second "Add Audit" for the same client used to hit that constraint and
 * surface Postgres's own wording verbatim: "duplicate key value violates
 * unique constraint \"tax_audits_client_id_financial_year_key\"", which
 * names a database object rather than a document the CA can go and open.
 *
 * The PRIMARY fix is upstream of this file: `AuditModal` now looks the row
 * up before saving and switches into editing it (see
 * app/income-tax/tax-audit/page.tsx's `existingMatch`). This is the
 * belt-and-braces half — the window that lookup cannot close (two people
 * saving the same client+FY at once, or the lookup itself failing silently,
 * both of which still reach the INSERT) — so even a genuine collision at the
 * database reads as something to do, not a stack of unfamiliar words.
 */

export interface PostgrestLikeError {
  code?: string | null;
  message?: string | null;
  hint?: string | null;
}

/** Postgres error code 23505 is `unique_violation`. Matched on the CODE —
 *  not on the message text, which is what actually reached the CA before —
 *  because a constraint's own wording can be reworded by a later migration
 *  while the code stays the code. Returns null for anything else, so a
 *  caller falls back to the error's own message unchanged. */
export function duplicateAuditErrorMessage(
  error: PostgrestLikeError | null | undefined,
): string | null {
  if (!error || error.code !== "23505") return null;
  return "An audit record for this client and financial year already exists "
    + "— edit it instead of adding another.";
}

/** The hint migration 584's trigger puts on its refusal: the audit was recorded as done with a day that has not come. */
export const AUDIT_DATE_REFUSAL_HINT = "tax_audits_dates_follow_the_status";

/** Migration 584 refuses an audit recorded as completed or filed with an audit date that has not come, and one recorded as filed with such a filing date, in a sentence written for
 *  a person (the dates are India's). It is raised as a check violation (23514) with the hint above; a CHECK constraint of the same table raises the same code in the database's
 *  own wording, which is NOT a sentence for a person, so the hint is what is matched. The message IS the sentence and is returned as it is. Null for anything else. */
export function auditDateRefusalMessage(
  error: PostgrestLikeError | null | undefined,
): string | null {
  if (!error || error.code !== "23514" || error.hint !== AUDIT_DATE_REFUSAL_HINT) return null;
  return typeof error.message === "string" && error.message.trim() ? error.message.trim() : null;
}
