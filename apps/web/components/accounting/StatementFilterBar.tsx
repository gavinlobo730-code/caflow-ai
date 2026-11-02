"use client";

import { NO_FILTER, isFiltering, statementFilterNotice, type FilterableRow, type TrialBalanceFilter, accountCounts, typeChoices } from "@/lib/accounting/trialBalanceFilter";

/**
 * The search box and account-type choice above the Profit and Loss and the Balance Sheet (POST-A-136).
 *
 * Both statements are presented by Schedule III caption, so a filter cannot hide a whole caption without making the figures stop adding
 * up on the page. It does the other thing: it chooses which ACCOUNT ROWS are drawn under each caption and nothing else. Every caption's
 * figure and every total stays the sum of all of its accounts, and the sentence under the box says so whenever a filter is on. The
 * sentence is not hidden when the page is printed, because a printed statement with rows left out has to say that it has.
 */
export function StatementFilterBar({ idPrefix, accounts, filter, onChange }: {
  idPrefix: string;
  /** Every account on the statement, before any filter. */
  accounts: readonly FilterableRow[];
  filter: TrialBalanceFilter;
  onChange: (next: TrialBalanceFilter) => void;
}) {
  const types = typeChoices(accounts);
  const { shown, total } = accountCounts(accounts, filter);
  const sentence = statementFilterNotice(shown, total, filter);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <label htmlFor={`${idPrefix}-search`} className="sr-only">Search accounts by code or name</label>
        <input id={`${idPrefix}-search`} type="search" value={filter.query} placeholder="Search by code or name"
          onChange={(e) => onChange({ ...filter, query: e.target.value })}
          className="text-xs px-2.5 py-1.5 border border-ps-border rounded-lg w-64 focus:outline-none focus:ring-1 focus:ring-brand" />
        {types.length > 1 && (
          <>
            <label htmlFor={`${idPrefix}-type`} className="sr-only">Account type</label>
            <select id={`${idPrefix}-type`} value={filter.type} onChange={(e) => onChange({ ...filter, type: e.target.value })}
              className="text-xs px-2.5 py-1.5 border border-ps-border rounded-lg bg-white">
              <option value="">All types</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </>
        )}
        {isFiltering(filter) && (
          <button type="button" onClick={() => onChange(NO_FILTER)} className="text-xs text-brand underline">Clear</button>
        )}
      </div>
      {sentence && <p role="status" className="text-xs text-ps-label">{sentence}</p>}
    </div>
  );
}
