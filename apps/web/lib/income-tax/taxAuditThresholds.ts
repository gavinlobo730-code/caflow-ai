/**
 * IT Act 1961, Section 44AB — tax-audit turnover/gross-receipts thresholds.
 * Values in integer paise (CLAUDE.md: never floating point).
 *
 * Note: Finance Act 2020 raises the business threshold to ₹10 crore, and
 * Finance Act 2023 raises the professional threshold to ₹75 lakh, when cash
 * receipts AND cash payments each stay within 5% of the total — that
 * cash-percentage test is not modeled here; callers always apply the base
 * (non-cash-limited) threshold below.
 */
export const THRESHOLD_BUSINESS_PAISE = 1_000_000_000; // Section 44AB(a): ₹1,00,00,000 (₹1 crore) turnover
export const THRESHOLD_PROFESSION_PAISE = 500_000_000; // Section 44AB(b): ₹50,00,000 (₹50 lakh) gross receipts
