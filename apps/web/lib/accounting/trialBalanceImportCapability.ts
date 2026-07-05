/**
 * Trial Balance Import feature-availability gate (C4).
 *
 * The importer writes opening_balance_dr_paise/opening_balance_cr_paise
 * directly onto chart_of_accounts — columns no migration has ever created
 * (verified: no apps/api/migrations/*.sql file adds them). The importer
 * previously ran its full wizard regardless, silently failing every row's
 * write and only THEN telling the user, after the fact, that a migration
 * was needed. This checks availability up front and gates the whole
 * workflow rather than exposing a wizard that cannot actually succeed.
 */
export interface TrialBalanceImportCapability {
  available: boolean;
  reason?: string;
}

const MISSING_COLUMN_MARKERS = ["opening_balance_dr_paise", "opening_balance_cr_paise"];

export async function checkTrialBalanceImportCapability(
  probe: () => Promise<{ error: { message: string } | null }>
): Promise<TrialBalanceImportCapability> {
  try {
    const { error } = await probe();
    if (!error) return { available: true };
    if (MISSING_COLUMN_MARKERS.some((m) => error.message.includes(m))) {
      return {
        available: false,
        reason:
          "This feature requires a database migration that hasn't been applied yet " +
          "(chart_of_accounts.opening_balance_dr_paise / opening_balance_cr_paise). " +
          "Ask your administrator to apply it before importing a trial balance.",
      };
    }
    return { available: false, reason: error.message };
  } catch (e) {
    return {
      available: false,
      reason: e instanceof Error ? e.message : "Unable to verify feature availability.",
    };
  }
}
