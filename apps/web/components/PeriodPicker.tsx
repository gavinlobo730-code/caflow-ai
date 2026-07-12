"use client";

import { PERIOD_OPTIONS, periodOptionLabel, GRANULARITY_OPTIONS, type PeriodMode, type Granularity } from "@/lib/dates/periods";

/**
 * QuickBooks-style period dropdown: Today / Yesterday / This Week / Last 3
 * Months / This Financial Year / Last Financial Year / Custom Range. Drop
 * into a page's toolbar next to search — the page owns the `mode`/custom
 * from-to state and resolves it to a concrete date range via
 * `resolvePeriodRange` (lib/dates/periods.ts) to scope its own query.
 *
 * Pass `granularity`/`onGranularityChange` to also render the "Display
 * columns by" split (Total/Monthly/Quarterly/Yearly) used by P&L/Balance
 * Sheet's multi-period comparison — omit both to get the plain single-range
 * picker used by transaction list pages (Sales Invoices, Purchase Bills).
 */
export default function PeriodPicker({
  mode, onModeChange, financialYear,
  customFrom, customTo, onCustomFromChange, onCustomToChange,
  granularity, onGranularityChange,
  ariaLabel = "Date range",
}: {
  mode: PeriodMode;
  onModeChange: (m: PeriodMode) => void;
  financialYear: string;
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
        value={mode}
        onChange={(e) => onModeChange(e.target.value as PeriodMode)}
        aria-label={ariaLabel}
        className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
      >
        {PERIOD_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{periodOptionLabel(o.value, financialYear)}</option>
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
