/**
 * Cash-flow arithmetic for the multi-period view.
 *
 * The Cash Flow tab can show one period or twelve. Rendering is the easy half;
 * the half worth testing is what happens to the NUMBERS when a single statement
 * becomes a row of them, because both mistakes available here are silent:
 *
 *   1. An account present in one column and absent from another is a ZERO in
 *      that column, not a missing row. Dropping it would make each column's
 *      account list differ from its neighbours', which destroys the comparison
 *      the split exists for.
 *   2. Flows add across contiguous periods; BALANCES DO NOT. Opening cash is
 *      the first column's opening and closing is the last column's closing.
 *      Summing those would count the cash on hand once per column — twelve
 *      times over a monthly year, and wrong by an amount that looks plausible.
 *
 * Everything here is presentation arithmetic over figures the backend already
 * computed (CLAUDE.md — no business logic in the frontend). Nothing is
 * classified, derived or re-stated: the AS-3 engine decided what is operating,
 * investing and financing, and these functions only line its answers up.
 */

export interface CFLine { account_id: string; account_name: string; amount_paise: number }
export interface CFSection { label: string; lines: CFLine[]; total_paise: number }
export interface CFRecon {
  net_profit_paise: number;
  non_operating_adjust_paise: number;
  depreciation_addback_paise: number;
  working_capital_change_paise: number;
  net_cash_operating_paise: number;
  ties_out: boolean;
}
export interface CFData {
  start_date: string;
  end_date: string;
  operating: CFSection;
  investing: CFSection;
  financing: CFSection;
  net_change_paise: number;
  opening_cash_paise: number;
  closing_cash_paise: number;
  reconciles: boolean;
  non_cash_excluded_count: number;
  operating_reconciliation: CFRecon;
}

/** One displayed period. `data` is null when that column's fetch failed — the
 *  other columns still render, so one slow month cannot blank the year. */
export interface CFColumn { label: string; start: string; end: string; data: CFData | null; error: boolean }

export type CFPick = (d: CFData) => CFSection;

/**
 * Accounts appearing in one section across every column, in first-seen order.
 *
 * Keyed on account_id, falling back to the name for a backend row that omits
 * it — two different accounts sharing a display name would otherwise collapse
 * into one row and silently add together.
 */
export function cfUnion(columns: CFColumn[], pick: CFPick): { id: string; name: string }[] {
  const seen = new Map<string, string>();
  for (const c of columns) {
    if (!c.data) continue;
    for (const l of pick(c.data).lines) {
      const id = l.account_id || l.account_name;
      if (!seen.has(id)) seen.set(id, l.account_name);
    }
  }
  return Array.from(seen, ([id, name]) => ({ id, name }));
}

/** One account's amount in one column — zero when the account did not move in
 *  that period, or when the column failed to load. */
export function cfAmount(data: CFData | null, pick: CFPick, id: string): number {
  if (!data) return 0;
  return pick(data).lines.find((l) => (l.account_id || l.account_name) === id)?.amount_paise ?? 0;
}

export interface CFAggregate {
  operating: number;
  investing: number;
  financing: number;
  netChange: number;
  opening: number;
  closing: number;
  reconciles: boolean;
  /** True when every column loaded. False means the totals cover only part of
   *  the window, so opening + netChange will not tie to closing and the UI must
   *  say so rather than show a figure quietly missing a period. */
  complete: boolean;
}

/**
 * The summary strip for the whole window, however it was split.
 *
 * splitPeriodColumns emits contiguous, non-overlapping columns covering the
 * range, which is what makes `opening + Σ netChange = closing` hold — see
 * cashFlowTiesOut() for the check itself. Returns null when nothing loaded.
 */
export function aggregateCashFlow(columns: CFColumn[]): CFAggregate | null {
  const withData = columns.filter((c): c is CFColumn & { data: CFData } => c.data !== null);
  if (!withData.length) return null;
  const sum = (f: (d: CFData) => number) => withData.reduce((s, c) => s + f(c.data), 0);
  return {
    operating: sum((d) => d.operating.total_paise),
    investing: sum((d) => d.investing.total_paise),
    financing: sum((d) => d.financing.total_paise),
    netChange: sum((d) => d.net_change_paise),
    // NOT summed. See the header note.
    opening: withData[0].data.opening_cash_paise,
    closing: withData[withData.length - 1].data.closing_cash_paise,
    reconciles: withData.every((c) => c.data.reconciles),
    complete: withData.length === columns.length,
  };
}

/**
 * Whether the aggregate is internally consistent: opening + net change =
 * closing. Integer paise throughout, so this is an exact equality and not a
 * tolerance — a cash flow statement that is off by one paise is off.
 */
export function cashFlowTiesOut(agg: CFAggregate | null): boolean {
  if (!agg) return true;
  return agg.opening + agg.netChange === agg.closing;
}
