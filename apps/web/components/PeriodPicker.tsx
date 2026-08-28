"use client";

import { periodChoices, encodePeriodChoice, decodePeriodChoice, GRANULARITY_OPTIONS, type PeriodMode, type Granularity } from "@/lib/dates/periods";

/**
 * Period dropdown: Today / Yesterday / This Week / Last 3 Months / each of
 * the last five financial years by name / All Time / Custom Range. Drop into
 * a page's toolbar next to search — the page owns the mode, the financial
 * year and the custom from-to, and resolves them to a concrete date range via
 * `resolvePeriodRange` (lib/dates/periods.ts) to scope its own query.
 *
 * THE FINANCIAL YEAR IS CHOSEN HERE, NOT ABOVE
 *   This control used to offer "This Financial Year" and "Last Financial
 *   Year", both relative to a year picked in the client header — a second
 *   control, on a different part of the screen, that no page was obliged to
 *   honour and half of them ignored. A CA could be looking at "FY 2026-27" in
 *   the header and "Last Financial Year (FY 2025-26)" in the filter, on one
 *   page, over rows belonging to one of them.
 *
 *   So the header selector was removed and the years are named outright. The
 *   filter that scopes the query is the only thing on screen claiming to say
 *   what period is shown, which means it cannot disagree with anything.
 *
 * Pass `granularity`/`onGranularityChange` to also render the "Display
 * columns by" split (Total/Monthly/Quarterly/Yearly) used by P&L/Balance
 * Sheet's multi-period comparison — omit both to get the plain single-range
 * picker used by transaction list pages (Sales Invoices, Purchase Bills).
 */
export default function PeriodPicker({
  mode, onModeChange, financialYear, onFinancialYearChange,
  customFrom, customTo, onCustomFromChange, onCustomToChange,
  granularity, onGranularityChange,
  ariaLabel = "Date range",
}: {
  mode: PeriodMode;
  onModeChange: (m: PeriodMode) => void;
  financialYear: string;
  onFinancialYearChange: (fy: string) => void;
  customFrom: string;
  customTo: string;
  onCustomFromChange: (v: string) => void;
  onCustomToChange: (v: string) => void;
  granularity?: Granularity;
  onGranularityChange?: (g: Granularity) => void;
  ariaLabel?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={encodePeriodChoice(mode, financialYear)}
        onChange={(e) => {
          const next = decodePeriodChoice(e.target.value, financialYear);
          // Order matters only if a caller re-renders between the two; both
          // are React state setters batched into one render, so the picker
          // never shows a mode and a year from different selections.
          if (next.financialYear !== financialYear) onFinancialYearChange(next.financialYear);
          onModeChange(next.mode);
        }}
        aria-label={ariaLabel}
        className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
      >
        {periodChoices().map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {mode === "custom" && (
        <>
          <input
            type="date"
            value={customFrom}
            onChange={(e) => onCustomFromChange(e.target.value)}
            aria-label="From date"
            className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
          />
          <span className="text-xs text-[#94A3B8]">to</span>
          <input
            type="date"
            value={customTo}
            onChange={(e) => onCustomToChange(e.target.value)}
            aria-label="To date"
            className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
          />
        </>
      )}
      {granularity && onGranularityChange && (
        <select
          value={granularity}
          onChange={(e) => onGranularityChange(e.target.value as Granularity)}
          aria-label="Display columns by"
          className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
        >
          {GRANULARITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>Display: {o.label}</option>
          ))}
        </select>
      )}
    </div>
  );
}
