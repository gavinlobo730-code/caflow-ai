/**
 * Monthly salary TDS estimate (IT Act §192), new tax regime, integer paise
 * throughout. Single shared copy for the payroll frontend (payroll/page.tsx,
 * payroll/reports/page.tsx) — before this module existed, the same
 * slab/rebate/surcharge numbers had drifted independently across those two
 * files and the backend engines (audit finding F17).
 *
 * STATUS — be honest about what this is: the intended authoritative engine
 * is apps/api/routers/payroll.py's _compute_tds_192 (FY-versioned via
 * apps/api/domain/income_tax/statutory_rates.py), and this module mirrors
 * its FY 2025-26 figures (cross-verified value-for-value against it). But
 * TODAY, payroll/page.tsx's "Generate Payslips" still PERSISTS slips
 * computed here via direct browser-side Supabase inserts, never reaching
 * the backend engine — so for that page this is load-bearing statutory
 * logic in the frontend, a standing CLAUDE.md violation tracked as roadmap
 * R2.10 (move payroll compute server-side; the clients/[id]/payroll page
 * already correctly posts to /api/payroll/runs). Until R2.10 lands, any
 * future FY's verified rate change MUST update BOTH this file and
 * statutory_rates.py, or persisted payroll slips will silently diverge
 * from the ITR/backend numbers. This module is deliberately NOT
 * FY-versioned — keeping it a single year's constants keeps the eventual
 * R2.10 deletion trivial and avoids growing a second rules registry.
 */

/**
 * New-regime FY2025-26 slab tax only (no rebate/surcharge/cess), in paise.
 * Mirrors slab_tax_paise(taxable, rates.new_regime_slabs) in the backend's
 * domain/income_tax/statutory_rates.py.
 */
export function slabTaxNewRegimePaise(taxable: number): number {
  if (taxable <= 40_000_000) return 0;                                                  // 0–4L: nil
  if (taxable <= 80_000_000) return Math.floor((taxable - 40_000_000) * 5 / 100);        // 4–8L: 5%
  if (taxable <= 120_000_000) return 2_000_000 + Math.floor((taxable - 80_000_000) * 10 / 100);   // 8–12L: 10%
  if (taxable <= 160_000_000) return 6_000_000 + Math.floor((taxable - 120_000_000) * 15 / 100);  // 12–16L: 15%
  if (taxable <= 200_000_000) return 12_000_000 + Math.floor((taxable - 160_000_000) * 20 / 100); // 16–20L: 20%
  if (taxable <= 240_000_000) return 20_000_000 + Math.floor((taxable - 200_000_000) * 25 / 100);  // 20–24L: 25%
  return 30_000_000 + Math.floor((taxable - 240_000_000) * 30 / 100);                    // >24L: 30%
}

/**
 * Section 2(29C) surcharge with marginal relief, new-regime 25% cap (Finance
 * Act 2023 dropped the 37% new-regime slab). Mirrors
 * apply_surcharge_with_marginal_relief in the backend's statutory_rates.py.
 */
export function surchargeNewRegimePaise(taxableAnnualPaise: number, taxPaise: number): number {
  const BRACKETS: { above: number; rate: number }[] = [
    { above: 500_000_000, rate: 10 },   // > ₹50L
    { above: 1_000_000_000, rate: 15 }, // > ₹1Cr
    { above: 2_000_000_000, rate: 25 }, // > ₹2Cr
    { above: 5_000_000_000, rate: 37 }, // > ₹5Cr (capped to 25% below, new regime)
  ];
  const NEW_REGIME_CAP = 25;

  let rate = 0;
  let threshold = 0;
  for (const b of BRACKETS) {
    if (taxableAnnualPaise > b.above) { rate = b.rate; threshold = b.above; }
  }
  rate = Math.min(rate, NEW_REGIME_CAP);
  if (rate === 0) return 0;

  let surcharge = Math.floor(taxPaise * rate / 100);
  const totalWithSurcharge = taxPaise + surcharge;
  const taxAtThreshold = slabTaxNewRegimePaise(threshold);
  const maxTotal = taxAtThreshold + (taxableAnnualPaise - threshold);
  if (totalWithSurcharge > maxTotal) {
    surcharge = Math.max(taxAtThreshold, maxTotal) - taxPaise;
  }
  return Math.max(0, surcharge);
}

/**
 * Monthly salary TDS under the new regime (IT Act §192), in integer paise.
 *
 * FY 2025-26 (Budget 2025 / Finance Act 2025 — VERIFIED, see
 * apps/api/domain/income_tax/statutory_rates.py, the backend's single source
 * of truth for these figures): standard deduction ₹75,000; slabs 0–4L nil,
 * 4–8L 5%, 8–12L 10%, 12–16L 15%, 16–20L 20%, 20–24L 25%, >24L 30%; §87A
 * rebate makes tax nil up to ₹12,00,000 taxable (with marginal relief just
 * above the ceiling); surcharge above ₹50L taxable (marginal relief at each
 * threshold, capped at 25% for the new regime); 4% health & education cess.
 *
 * Input and output are PAISE. An earlier version compared a paise-scale
 * annual gross against rupee-scale thresholds (e.g. `annualGross > 1500000`
 * meaning ₹15,000 instead of ₹15,00,000) while the base amounts were paise,
 * so it massively over-deducted (finding F15). It later also carried stale
 * FY 2023-24 slabs/rebate ceiling and omitted surcharge entirely, and a
 * second, independently-drifted copy existed for a TDS projection feature
 * (finding F17). NOTE: this statutory logic belongs server-side — the
 * payroll compute should route through the backend (POST /api/payroll/runs,
 * which uses the FY-versioned statutory_rates.py engine). Kept here,
 * corrected and de-duplicated, as a live pre-save preview / projection only,
 * until that migration lands (roadmap R2.10).
 */
export function monthlyTdsPaiseNewRegime(annualGrossPaise: number): number {
  const STD_DEDUCTION = 7_500_000;    // ₹75,000 in paise (new regime)
  const REBATE_CEIL = 120_000_000;    // ₹12,00,000 taxable in paise (§87A)
  const taxable = Math.max(0, annualGrossPaise - STD_DEDUCTION);
  if (taxable <= REBATE_CEIL) return 0;

  let tax = slabTaxNewRegimePaise(taxable);
  // §87A marginal relief: tax cannot exceed the income above the ₹12,00,000 ceiling.
  tax = Math.min(tax, taxable - REBATE_CEIL);

  const surcharge = surchargeNewRegimePaise(taxable, tax);
  let total = tax + surcharge;
  total = total + Math.floor(total * 4 / 100);   // 4% health & education cess
  return Math.floor(total / 12);
}
