// The fixed-deposit register's maturity amount: the receipt's figure or a flagged estimate. Run with:
//   node --experimental-strip-types --test lib/loans/fdMaturity.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { chooseMaturity, estimateFDMaturityPaise, isEstimate } from "./fdMaturity.ts";

const LAKH = 100_000_00; // Rs 1,00,000 in paise

test("the estimate is annual compounding in whole paise", () => {
  // 365 days at 7% -> one year of interest on a lakh.
  assert.equal(estimateFDMaturityPaise(LAKH, 7, "2026-04-01", "2027-04-01"), 107_000_00);
  // Two years: 1.07^2 = 1.1449.
  assert.equal(estimateFDMaturityPaise(LAKH, 7, "2026-04-01", "2028-03-31"), Math.round(LAKH * Math.pow(1.07, 730 / 365)));
});

test("a missing or reversed date range is the principal, not a made-up figure", () => {
  assert.equal(estimateFDMaturityPaise(LAKH, 7, "", "2027-04-01"), LAKH);
  assert.equal(estimateFDMaturityPaise(LAKH, 7, "2027-04-01", "2026-04-01"), LAKH);
});

test("a blank receipt box stores the estimate, flagged", () => {
  assert.deepEqual(chooseMaturity("", LAKH, 107_000_00), { ok: true, paise: 107_000_00, isEstimate: true });
  assert.deepEqual(chooseMaturity("   ", LAKH, 107_000_00), { ok: true, paise: 107_000_00, isEstimate: true });
});

test("a typed receipt amount is stored as typed, not flagged, with grouping and the rupee sign tolerated", () => {
  assert.deepEqual(chooseMaturity("1,07,186.50", LAKH, 107_000_00), { ok: true, paise: 107_186_50, isEstimate: false });
  assert.deepEqual(chooseMaturity("₹ 107186", LAKH, 107_000_00), { ok: true, paise: 107_186_00, isEstimate: false });
});

test("a typed amount that is not an amount, is zero or is below the principal is refused in words", () => {
  for (const bad of ["abc", "1e5", "0", "-5", "1.2.3"]) {
    const r = chooseMaturity(bad, LAKH, 107_000_00);
    assert.equal(r.ok, false, bad);
  }
  const below = chooseMaturity("99000", LAKH, 107_000_00);
  assert.equal(below.ok, false);
  assert.match((below as { error: string }).error, /below the principal/);
  // exactly the principal is allowed (a zero-interest deposit)
  assert.equal(chooseMaturity("100000", LAKH, 107_000_00).ok, true);
});

test("a row without the flag is an estimate", () => {
  assert.equal(isEstimate({}), true);
  assert.equal(isEstimate({ maturity_amount_is_estimate: null }), true);
  assert.equal(isEstimate({ maturity_amount_is_estimate: true }), true);
  assert.equal(isEstimate({ maturity_amount_is_estimate: false }), false);
});
