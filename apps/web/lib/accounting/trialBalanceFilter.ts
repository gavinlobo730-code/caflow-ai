/**
 * Narrowing the trial balance on screen to the accounts a person is looking for (POST-A-136).
 *
 * A trial balance is the whole ledger's accounts in one column, and a practice looks for one account in it (cash, a creditor, TDS
 * payable) more often than it reads it top to bottom. The search and the type filter only choose which ROWS are drawn: every total on
 * the screen is the server's, for all of the accounts, and the screen says so whenever a filter is on. Nothing here adds up a rupee.
 *
 * A row the server COMPUTES rather than reads from an account (the brought-forward surplus, whose id starts `__`) is not an account and
 * cannot be searched for, so it is drawn only when no filter is on. The two cash-basis ADVANCE accounts also have an id that starts `__`, but
 * they are accounts: named, typed, with a balance that is inside the server's totals, so a search finds them and the counts include them.
 */
export interface FilterableRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
}

export interface TrialBalanceFilter {
  /** What was typed in the search box. Matched against the account's code and its name, ignoring case and surrounding spaces. */
  query: string;
  /** An account type exactly as the rows carry it, or "" for all types. */
  type: string;
}

export const NO_FILTER: TrialBalanceFilter = { query: "", type: "" };

/**
 * The accounts the cash-basis projection registers when a chart has no advance control account (`domain/reporting/projector.ADVANCE_CUSTOMER`
 * and `ADVANCE_VENDOR`). Their ids start `__` because they are not rows of `chart_of_accounts`, but they are accounts on the report: a name, a
 * type and a balance that the totals include. `apps/api/tests/test_the_trial_balance_filter_knows_the_engines_synthetic_accounts.py` holds this
 * list to the engine's, so a third one added there cannot be left out here.
 */
export const SYNTHETIC_ACCOUNT_IDS: readonly string[] = ["__advance_customers__", "__advance_to_vendors__"];

/** A row the server computed (the brought-forward surplus, the retained-earnings line): not an account. */
const isDerived = (row: FilterableRow) => row.account_id.startsWith("__") && !SYNTHETIC_ACCOUNT_IDS.includes(row.account_id);

export const isFiltering = (filter: TrialBalanceFilter): boolean => filter.query.trim() !== "" || filter.type !== "";

/** The rows to draw, in the order the server sent them. */
export function filterRows<T extends FilterableRow>(rows: readonly T[], filter: TrialBalanceFilter): T[] {
  if (!isFiltering(filter)) return [...rows];
  const needle = filter.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (isDerived(row)) return false;
    if (filter.type !== "" && row.account_type !== filter.type) return false;
    if (needle === "") return true;
    return row.account_code.toLowerCase().includes(needle) || row.account_name.toLowerCase().includes(needle);
  });
}

/** The account types present in the rows, in the order they first appear. The types are the server's words and are not translated. */
export function typeChoices(rows: readonly FilterableRow[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) if (!isDerived(row) && row.account_type) seen.add(row.account_type);
  return Array.from(seen);
}

/**
 * The rows to draw under a Profit and Loss or Balance Sheet caption. The same filter as the trial balance's for the accounts (the cash-basis
 * advance accounts among them), but a DERIVED row (the computed retained earnings / net profit line) is drawn under EVERY filter: on these
 * statements it is a component of its caption's figure and of the total beside it, not an account to search for, so hiding it would leave a
 * caption whose drawn rows do not reconcile to its figure and no filter that could show the line (a review of 2-11-2026 found exactly that).
 * It is still not counted among the accounts.
 */
export function filterStatementRows<T extends FilterableRow>(rows: readonly T[], filter: TrialBalanceFilter): T[] {
  if (!isFiltering(filter)) return [...rows];
  return rows.filter((row) => isDerived(row) || filterRows([row], filter).length === 1);
}

/** How many of the accounts the filter lets through, and how many there are. Derived rows are not accounts and are not counted. */
export function accountCounts<T extends FilterableRow>(rows: readonly T[], filter: TrialBalanceFilter): { shown: number; total: number } {
  const accounts = rows.filter((row) => !isDerived(row));
  return { shown: filterRows(accounts, filter).length, total: accounts.length };
}

/** The sentence under the toolbar while a filter is on, saying what the totals are totals OF; null when nothing is filtered. */
export function filterNotice(shown: number, total: number, filter: TrialBalanceFilter): string | null {
  if (!isFiltering(filter)) return null;
  const word = (n: number) => `${n} account${n === 1 ? "" : "s"}`;
  return `Showing ${shown} of ${word(total)}. The totals below are for all ${total}, not only the ones shown.`;
}

/**
 * The sentence above a Profit and Loss or Balance Sheet while a filter is on. The statements are laid out by Schedule III caption, so the
 * figures that stay whole are the CAPTIONS' as well as the totals; null when nothing is filtered.
 */
export function statementFilterNotice(shown: number, total: number, filter: TrialBalanceFilter): string | null {
  if (!isFiltering(filter)) return null;
  const word = (n: number) => `${n} account${n === 1 ? "" : "s"}`;
  return `Showing ${shown} of ${word(total)}. Each caption's figure and every total are for all ${total}, not only the ones shown.`;
}
