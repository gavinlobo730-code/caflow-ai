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
