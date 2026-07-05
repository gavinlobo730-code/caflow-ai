// Section 44AB tax-audit threshold tests (H7) — run with:
//   node --experimental-strip-types --test lib/income-tax/taxAuditThresholds.test.ts
//
// THRESHOLD_BUSINESS/THRESHOLD_PROFESSION were previously 10x too small (a
// paise/rupee conversion bug: ₹1 crore was encoded as ₹10 lakh in paise, and
// ₹50 lakh as ₹5 lakh), flagging tax audits ~10x too early. These pin the
// exact statutory rupee values (in paise) and the below/at/above threshold
// behavior used by the Tax Audit Tracker page.
import test from "node:test";
import assert from "node:assert/strict";
import { THRESHOLD_BUSINESS_PAISE, THRESHOLD_PROFESSION_PAISE } from "./taxAuditThresholds.ts";

// Mirrors the Tax Audit Tracker page's own comparison (>= threshold).
function requiresBusinessAudit(turnoverPaise: number): boolean {
  return turnoverPaise >= THRESHOLD_BUSINESS_PAISE;
}
function requiresProfessionAudit(receiptsPaise: number): boolean {
  return receiptsPaise >= THRESHOLD_PROFESSION_PAISE;
}

test("business threshold is exactly ₹1,00,00,000 (₹1 crore) in paise", () => {
  assert.equal(THRESHOLD_BUSINESS_PAISE, 1_00_00_000 * 100);
  assert.equal(THRESHOLD_BUSINESS_PAISE / 100, 1_00_00_000); // ₹1 crore in rupees
});

test("profession threshold is exactly ₹50,00,000 (₹50 lakh) in paise", () => {
  assert.equal(THRESHOLD_PROFESSION_PAISE, 50_00_000 * 100);
  assert.equal(THRESHOLD_PROFESSION_PAISE / 100, 50_00_000); // ₹50 lakh in rupees
});

test("business turnover below ₹1 crore does not require a tax audit", () => {
  assert.equal(requiresBusinessAudit(THRESHOLD_BUSINESS_PAISE - 1), false);
  assert.equal(requiresBusinessAudit(99_00_000 * 100), false); // ₹99 lakh
});

test("business turnover exactly ₹1 crore requires a tax audit", () => {
  assert.equal(requiresBusinessAudit(THRESHOLD_BUSINESS_PAISE), true);
});

test("business turnover above ₹1 crore requires a tax audit", () => {
  assert.equal(requiresBusinessAudit(THRESHOLD_BUSINESS_PAISE + 1), true);
  assert.equal(requiresBusinessAudit(2_00_00_000 * 100), true); // ₹2 crore
});

test("professional receipts below ₹50 lakh do not require a tax audit", () => {
  assert.equal(requiresProfessionAudit(THRESHOLD_PROFESSION_PAISE - 1), false);
  assert.equal(requiresProfessionAudit(49_00_000 * 100), false); // ₹49 lakh
});

test("professional receipts exactly ₹50 lakh require a tax audit", () => {
  assert.equal(requiresProfessionAudit(THRESHOLD_PROFESSION_PAISE), true);
});

test("professional receipts above ₹50 lakh require a tax audit", () => {
  assert.equal(requiresProfessionAudit(THRESHOLD_PROFESSION_PAISE + 1), true);
  assert.equal(requiresProfessionAudit(60_00_000 * 100), true); // ₹60 lakh
});

test("a ₹10 lakh turnover no longer false-flags a business tax audit (the H7 regression)", () => {
  // The old buggy constant (10_00_00_000 / 100 = ₹10 lakh) would have made
  // this true; a genuine ₹10 lakh turnover must never trigger the advisory.
  assert.equal(requiresBusinessAudit(10_00_000 * 100), false);
});
