"use client";

import { financialYearChoices } from "@/lib/dates/periods";

/**
 * A plain "which financial year" dropdown, for pages whose entire period is a
 * financial year — Overview's activity feed, Fixed Assets, Inventory,
 * Compliance, Documents, the client Portal.
 *
 * WHY THIS IS A PAGE CONTROL AND NOT A GLOBAL ONE
 *   It used to be one selector in the client header, shared by every page.
 *   Eleven pages read it; the rest ignored it, so it sat above screens it had
 *   no bearing on. And on the pages that DID read it, it competed with the
 *   page's own period filter: a CA could see "FY 2026-27" in the header and
 *   "Last Financial Year (FY 2025-26)" in the filter below, both true,
 *   describing different periods, over one table of rows.
 *
 *   A period control belongs next to the thing it scopes. Pages that need a
 *   year now say so themselves, and a page that shows no such control is a
 *   page where the year genuinely does not apply.
 *
 * Pages with a full date-range filter use PeriodPicker instead — it offers the
 * same financial years alongside Today / This Week / Custom Range, so a page
 * never carries both controls.
 */
export default function FinancialYearPicker({
  value,
  onChange,
  ariaLabel = "Financial year",
  className = "",
}: {
  value: string;
  onChange: (fy: string) => void;
  ariaLabel?: string;
  className?: string;
}) {
  const choices = financialYearChoices();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      className={`px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569] ${className}`}
    >
      {/* A year outside the offered window — reached by an old bookmark, or a
          client whose books start further back — is added rather than silently
          snapped to the nearest choice, which would change what is on screen
          without saying so. */}
      {(choices.includes(value) ? choices : [value, ...choices]).map((fy) => (
        <option key={fy} value={fy}>FY {fy}</option>
      ))}
    </select>
  );
}
