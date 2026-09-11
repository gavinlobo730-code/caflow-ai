/**
 * Schedule III (Companies Act 2013, Parts I & II) presentation caption
 * classification, mirroring the authoritative Python implementation in
 * domain/reporting/schedule_iii.py (pl_bucket / bs_bucket).
 *
 * The backend attaches its own computed caption to every P&L line AND every
 * Balance Sheet line (builders.py's schedule_iii_caption field) — these
 * functions are used ONLY as a fallback for the brief window where the
 * frontend has redeployed ahead of the backend. Pulled into their own module
 * (instead of living inline in accounting/page.tsx) so they're importable from
 * a plain test file — that file has JSX, which the project's Node test runner
 * can't parse, and untestable classification logic is exactly what let two
 * caption-string mismatches (one live, one latent) ship unnoticed on
 * 2026-07-25.
 *
 * WHAT A FALLBACK CAN AND CANNOT DO, because it is the whole reason the
 * Balance Sheet had to stop using this one as its primary source.
 *
 * These functions see a type and a subtype. They do NOT see the account's
 * `schedule_iii_mapping` — the CA's explicit choice on the mapping screen —
 * because that column is not on the line. So a mapped account classified here
 * is classified as if nobody had ever mapped it. Measured against production
 * on 11-09-2026, with the Balance Sheet grouping by bsBucket: 13 of the 26
 * mapped balance-sheet accounts were presented under a different caption than
 * the year-end statements gave them, including a Long-term Investment shown as
 * Other Current Assets.
 *
 * That is tolerable for ONE deploy's worth of skew and unacceptable as a
 * steady state, which is the difference between a fallback and a second
 * implementation.
 *
 * THE STRINGS BELOW ARE THE ENGINE'S, EXACTLY. They were not, until
 * 11-09-2026: this module said Tangible Assets / Intangible Assets /
 * Non-Current Investments where domain/reporting/schedule_iii.py says Tangible
 * Fixed Assets / Intangible Fixed Assets / Long-term Investments, and it had a
 * "Tax Liabilities" the engine has never had. A fallback that returns a
 * caption the engine does not know is not a fallback — it is the drift it was
 * meant to cover for. scheduleIiiCaptions.test.ts pins every one of them to
 * the list the API serves.
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
      return "Employee Benefits Expense";
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
      return "Intangible Fixed Assets";
    if (s.includes("fixed") || s.includes("plant") || s.includes("machinery") || s.includes("building") ||
        s.includes("furniture") || s.includes("vehicle") || s.includes("tangible") || s.includes("equipment"))
      return "Tangible Fixed Assets";
    if (s.includes("investment")) return "Long-term Investments";
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
    // NOT "Tax Liabilities". That caption exists nowhere in Schedule III and
    // nowhere in the engine; it was this module's own invention, and five tax
    // accounts in production that the CA had mapped to Other Current
    // Liabilities were displayed under it. Schedule III Part I puts statutory
    // dues in Other Current Liabilities, which is also what
    // domain/reporting/schedule_iii.py returns.
    if (s.includes("tax") || s.includes("gst") || s.includes("tds") || s.includes("duty"))
      return "Other Current Liabilities";
    return "Other Current Liabilities";
  }
  if (type === "Equity") {
    if (s.includes("capital") || s.includes("share")) return "Share Capital";
    return "Reserves & Surplus";
  }
  return "Other";
}

// The ORDER a statement presents its captions in. Kept in the engine's own
// order (domain/reporting/schedule_iii.py's PROFIT_LOSS_CAPTIONS /
// BALANCE_SHEET_CAPTIONS) and pinned to it by scheduleIiiCaptions.test.ts.
//
// A caption missing from one of these lists is not lost — the screens render
// anything uncovered in an "extra" group — but it appears out of order and
// outside the statement's shape.
//
// "Tax Expense" is missing from PL_EXP_ORDER ON PURPOSE and stays missing.
// Schedule III Part II presents tax BELOW profit before tax, and this tab has
// no below-the-line row; listing it among the operating expenses would fold it
// into total expenses, which is a worse presentation than the extra-bucket
// fallback that renders it separately. scheduleIiiCaptions.test.ts pins the
// exception so it cannot be "tidied" back in — which is what nearly happened
// on 11-09-2026 while the captions were being aligned to the engine.
export const PL_REV_ORDER = ["Revenue from Operations", "Other Income"];
export const PL_EXP_ORDER = [
  "Cost of Materials Consumed", "Employee Benefits Expense", "Finance Costs",
  "Depreciation & Amortisation", "Other Expenses",
];

export const BS_ASSET_ORDER = [
  "Tangible Fixed Assets", "Intangible Fixed Assets", "Long-term Investments", "Inventories",
  "Trade Receivables", "Short-term Loans & Advances", "Cash & Cash Equivalents", "Other Current Assets",
];
export const BS_LIAB_ORDER = [
  // "Deferred Tax Liability" is the engine's and was absent here, so a client
  // carrying one saw it in the uncovered group rather than among the
  // non-current liabilities where Schedule III puts it. "Tax Liabilities" is
  // gone: see bsBucket.
  "Long-term Borrowings", "Short-term Borrowings", "Deferred Tax Liability",
  "Trade Payables", "Other Current Liabilities",
];
export const BS_EQ_ORDER = ["Share Capital", "Reserves & Surplus"];
