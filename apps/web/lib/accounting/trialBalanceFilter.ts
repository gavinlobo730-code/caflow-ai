/**
 * Narrowing the trial balance on screen to the accounts a person is looking for (POST-A-136).
 *
 * A trial balance is the whole ledger's accounts in one column, and a practice looks for one account in it (cash, a creditor, TDS
 * payable) more often than it reads it top to bottom. The search and the type filter only choose which ROWS are drawn: every total on
 * the screen is the server's, for all of the accounts, and the screen says so whenever a filter is on. Nothing here adds up a rupee.
 *
 * A row the server derives rather than reads from an account (the brought-forward surplus, whose id starts `__`) is not an account and
 * cannot be searched for, so it is drawn only when no filter is on.
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

const isDerived = (row: FilterableRow) => row.account_id.startsWith("__");

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
