// Trial Balance Import capability-gate tests (C4) — run with:
//   node --experimental-strip-types --test lib/accounting/trialBalanceImportCapability.test.ts
//
// No migration in apps/api/migrations/*.sql has ever added
// chart_of_accounts.opening_balance_dr_paise/opening_balance_cr_paise. The
// importer previously ran its full wizard regardless and only discovered
// this after silently failing every row's write. This gates the workflow
// on a proactive check instead.
import test from "node:test";
import assert from "node:assert/strict";
import { checkTrialBalanceImportCapability } from "./trialBalanceImportCapability.ts";

test("migration present: probe succeeds -> feature is available", async () => {
  const result = await checkTrialBalanceImportCapability(async () => ({ error: null }));
  assert.deepEqual(result, { available: true });
});

test("migration missing: probe errors on the missing column -> feature is disabled with an explanatory reason", async () => {
  const result = await checkTrialBalanceImportCapability(async () => ({
    error: { message: "column chart_of_accounts.opening_balance_dr_paise does not exist" },
  }));
  assert.equal(result.available, false);
  assert.match(result.reason ?? "", /migration/i);
  assert.match(result.reason ?? "", /opening_balance_dr_paise/);
});

test("migration missing (credit column variant) is also recognized", async () => {
  const result = await checkTrialBalanceImportCapability(async () => ({
    error: { message: "Could not find the 'opening_balance_cr_paise' column of 'chart_of_accounts' in the schema cache" },
  }));
  assert.equal(result.available, false);
  assert.match(result.reason ?? "", /migration/i);
});

test("disabled state for an unrelated error surfaces that error directly, not a generic migration message", async () => {
  const result = await checkTrialBalanceImportCapability(async () => ({
    error: { message: "permission denied for table chart_of_accounts" },
  }));
  assert.equal(result.available, false);
  assert.equal(result.reason, "permission denied for table chart_of_accounts");
});

test("a thrown/rejected probe is treated as unavailable, never as available", async () => {
  const result = await checkTrialBalanceImportCapability(async () => {
    throw new Error("network error");
  });
  assert.equal(result.available, false);
  assert.equal(result.reason, "network error");
});
