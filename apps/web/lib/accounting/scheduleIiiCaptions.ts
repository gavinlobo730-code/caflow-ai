/**
 * Schedule III (Companies Act 2013, Parts I & II) presentation caption
 * classification, mirroring the authoritative Python implementation in
 * domain/reporting/schedule_iii.py (pl_bucket / bs_bucket).
 *
 * The backend now attaches its own computed caption to every P&L line
 * (builders.profit_loss()'s schedule_iii_caption field) — these functions are
 * used ONLY as a fallback for the brief window where the frontend has
 * redeployed ahead of the backend. Pulled into their own module (instead of
 * living inline in accounting/page.tsx) so they're importable from a plain
 * test file — that file has JSX, which the project's Node test runner can't
 * parse, and untestable classification logic is exactly what let two
 * caption-string mismatches (one live, one latent) ship unnoticed on
 * 2026-07-25.
 */

// Schedule III P&L bucket — Companies Act 2013, Schedule III, Part II
export function plBucket(type: string, subtype: string | null): string {
  const s = (subtype ?? "").toLowerCase();
  if (type === "Revenue") {
    if (s.includes("other income") || s.includes("non-operating")) return "Other Income";
    return "Revenue from Operations";
  }
  if (type === "Expense") {
    // Precise phrases only — mirrors domain/reporting/schedule_iii.py::pl_bucket
    // exactly. A bare s.includes("cost") here previously also matched "Finance
    // Costs" (and would match "Employee Cost"), misfiling it as "Cost of
    // Materials Consumed" before the finance-specific check below ever ran —
    // caught alongside the "Cost of Materials" vs "Cost of Materials Consumed"
    // mismatch on 2026-07-25, though this one was still latent (only reachable
    // via this fallback, which the live backend caption currently bypasses).
    if (s.includes("material") || s.includes("cost of goods") || s.includes("cogs") || s.includes("purchase"))
      return "Cost of Materials Consumed";
    if (s.includes("employee") || s.includes("salary") || s.includes("payroll") || s.includes("wages") || s.includes("staff"))
      return "Employee Benefit Expense";
    if (s.includes("depreciation") || s.includes("amortisation") || s.includes("amortization"))
      return "Depreciation & Amortisation";
    if (s.includes("finance") || s.includes("interest") || s.includes("bank charge") || s.includes("borrowing cost"))
      return "Finance Costs";
    if (s.includes("tax")) return "Tax Expense";
    return "Other Expenses";
  }
  return "Other";
}

// Schedule III Balance Sheet bucket — Companies Act 2013, Schedule III, Part I
export function bsBucket(type: string, subtype: string | null): string {
  const s = (subtype ?? "").toLowerCase();
  if (type === "Asset") {
    if (s.includes("intangible") || s.includes("goodwill") || s.includes("patent") || s.includes("trademark"))
      return "Intangible Assets";
    if (s.includes("fixed") || s.includes("plant") || s.includes("machinery") || s.includes("building") ||
        s.includes("furniture") || s.includes("vehicle") || s.includes("tangible") || s.includes("equipment"))
      return "Tangible Assets";
    if (s.includes("investment")) return "Non-Current Investments";
    if (s.includes("receivable") || s.includes("debtor")) return "Trade Receivables";
    if (s.includes("cash") || s.includes("bank")) return "Cash & Cash Equivalents";
    if (s.includes("inventor") || s.includes("stock")) return "Inventories";
    if (s.includes("prepaid") || s.includes("advance")) return "Short-term Loans & Advances";
    return "Other Current Assets";
  }
  if (type === "Liability") {
    if (s.includes("payable") || s.includes("creditor")) return "Trade Payables";
    // Short-term FIRST: the seeded subtype "Short Term Loan" contains "term
    // loan", so testing long-term first presented every working-capital loan
    // as a non-current borrowing (same fix as domain/reporting/schedule_iii.py).
    if (s.includes("short term") || s.includes("overdraft") || s.includes("cc limit") || s.includes("cash credit"))
      return "Short-term Borrowings";
    if (s.includes("long term") || s.includes("term loan") || s.includes("debenture") || s.includes("mortgage"))
      return "Long-term Borrowings";
    if (s.includes("tax") || s.includes("gst") || s.includes("tds") || s.includes("duty"))
      return "Tax Liabilities";
    return "Other Current Liabilities";
  }
  if (type === "Equity") {
    if (s.includes("capital") || s.includes("share")) return "Share Capital";
    return "Reserves & Surplus";
  }
  return "Other";
}

export const PL_REV_ORDER = ["Revenue from Operations", "Other Income"];
export const PL_EXP_ORDER = [
  "Cost of Materials Consumed", "Employee Benefit Expense", "Finance Costs",
  "Depreciation & Amortisation", "Other Expenses",
];
