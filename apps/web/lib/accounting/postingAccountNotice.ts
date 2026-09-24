/**
 * Did this receipt or payment post to the firm's GENERIC Bank ledger?
 *
 * THE AUTHORITY IS `apps/api/domain/accounting/payment_account.row_notice`,
 * and every API response for a receipt or a purchase payment already carries
 * its answer as `posting_account_notice`. Prefer that. This module is the
 * keystroke mirror, and it exists for one concrete reason: the client Sales
 * tab reads `receipts` STRAIGHT OVER POSTGREST, so no API response reaches it
 * and there is nothing served to render.
 *
 * The alternative was moving a working screen onto the API purely to render
 * one sentence. This repository already takes the mirror trade for GSTIN, UQC,
 * invoice numbers, GST line tax, the e-way threshold and IRN scope: one
 * authority, one mirror, one fixture both suites read —
 * `apps/api/tests/fixtures/posting_account_notice.json`, pinned FROM THE
 * PYTHON SIDE so a guard cannot assert this file against a copy of itself.
 *
 * WHAT IT CANNOT SEE, and why that is not a defect. Two of the three fallbacks
 * are facts about the chart of accounts at the moment of posting — a bank
 * account with no ledger of its own, a client with no Cash in Hand — and a row
 * cannot see either without a lookup per row. Those reach the CA in the
 * posting confirmation instead. A row with no notice is not a claim that the
 * posting was attributable.
 */

/** The modes that mean physical cash. `domain/accounting/payment_account.
 *  CASH_PAYMENT_MODES` is the authority and the fixture pins this list to it. */
const CASH_MODES = new Set(["cash", "petty_cash"]);

/** Fold a payment_mode to one spelling — lowercase, both SPACE and HYPHEN
 *  unified. Both, not one: the server's first version normalised the hyphen on
 *  the input and the space on the constant, so "petty cash" (the spelling a
 *  human types) matched neither and was read as a bank payment. */
function normaliseMode(mode: string | null | undefined): string {
  return String(mode ?? "").trim().toLowerCase().split(/\s+/).join("_").replace(/-/g, "_");
}

export function isCashMode(mode: string | null | undefined): boolean {
  return CASH_MODES.has(normaliseMode(mode));
}

export const POSTING_ACCOUNT_NOTICE =
  "No bank account was recorded on this document, so it posted to the firm's " +
  "general Bank ledger. Set the account to attribute it.";

/**
 * The sentence, or null where the posting named its own ledger.
 *
 * An EMPTY bank_account_id is not an account: the column is nullable and a
 * blank string reaches it from a form whose picker was cleared.
 */
export function postingAccountNotice(
  bankAccountId: string | null | undefined,
  paymentMode: string | null | undefined,
): string | null {
  const named = Boolean(bankAccountId);
  return !named && !isCashMode(paymentMode) ? POSTING_ACCOUNT_NOTICE : null;
}
