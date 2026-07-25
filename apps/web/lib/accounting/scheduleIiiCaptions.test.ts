// Schedule III caption classification tests — run with:
//   node --experimental-strip-types --test lib/accounting/scheduleIiiCaptions.test.ts
//
// This pins the same caption vocabulary that
// apps/api/tests/test_profit_loss_schedule_iii_caption.py pins on the Python
// side (domain/reporting/schedule_iii.py::pl_bucket). The two aren't
// automatically cross-checked (no shared runner across languages), so a
// caption added on one side without updating the other is a silent drift
// risk — that mismatch is exactly what made Cost of Goods Sold vanish from
// the P&L tab on 2026-07-25 even after the backend was fixed. Keep both
// files' known-vocabulary lists in sync by hand when either changes.
import test from "node:test";
import assert from "node:assert/strict";
import {
  plBucket, bsBucket, PL_REV_ORDER, PL_EXP_ORDER, BS_ASSET_ORDER, BS_LIAB_ORDER, BS_EQ_ORDER,
} from "./scheduleIiiCaptions.ts";

test("Cost of Goods Sold and Purchases share the Cost of Materials Consumed caption", () => {
  assert.equal(plBucket("Expense", "Cost of Goods Sold"), "Cost of Materials Consumed");
  assert.equal(plBucket("Expense", "Purchases"), "Cost of Materials Consumed");
  assert.equal(plBucket("Expense", "Raw Material"), "Cost of Materials Consumed");
});

test("Finance Costs is not misfiled under Cost of Materials Consumed", () => {
  // Regression pin: a bare `s.includes("cost")` check here previously matched
  // "Finance Costs" before the finance-specific branch ever ran, since "cost"
  // is a substring of "cost" in "Finance Costs" — latent until this fallback
  // path is actually exercised (i.e. the backend caption is ever missing).
  assert.equal(plBucket("Expense", "Finance Costs"), "Finance Costs");
  assert.equal(plBucket("Expense", "Bank Charges"), "Finance Costs");
});

test("every caption plBucket can produce for a Revenue account is in PL_REV_ORDER", () => {
  const subtypes = ["Operating Revenue", null, "Other Income", "Non-Operating Income", "Something New"];
  for (const s of subtypes) assert.ok(PL_REV_ORDER.includes(plBucket("Revenue", s)));
});

test("plBucket's known Expense captions — Tax Expense is the one deliberate exception", () => {
  // Tax Expense is intentionally NOT in PL_EXP_ORDER (this simpler tab, unlike
  // the full Schedule III statement, has no separate below-the-line tax
  // row) — the page's "extra bucket" fallback renders it anyway rather than
  // dropping it, but it's still not part of the ideal fixed order.
  const knownInOrder = ["Cost of Goods Sold", "Purchases", "Employee Cost", "Finance Costs", "Depreciation", null, "Rent"];
  for (const s of knownInOrder) assert.ok(PL_EXP_ORDER.includes(plBucket("Expense", s)), `unexpected caption for subtype ${s}`);
  assert.equal(plBucket("Expense", "Income Tax"), "Tax Expense");
  assert.ok(!PL_EXP_ORDER.includes("Tax Expense"));
});

test("every caption bsBucket can produce for a known Asset/Liability/Equity subtype is in the BS_*_ORDER lists", () => {
  const assetSubtypes = ["Plant & Machinery", "Goodwill", "Long Term Investment", "Inventory", "Trade Receivables",
    "Advance to Suppliers", "Bank Account", "Prepaid Expenses", null, "Something New"];
  for (const s of assetSubtypes) assert.ok(BS_ASSET_ORDER.includes(bsBucket("Asset", s)), `unexpected caption for asset subtype ${s}`);

  const liabSubtypes = ["Term Loan", "Bank Overdraft", "Trade Payables", "GST Payable", null, "Something New"];
  for (const s of liabSubtypes) assert.ok(BS_LIAB_ORDER.includes(bsBucket("Liability", s)), `unexpected caption for liability subtype ${s}`);

  const eqSubtypes = ["Share Capital", "Retained Earnings", null];
  for (const s of eqSubtypes) assert.ok(BS_EQ_ORDER.includes(bsBucket("Equity", s)), `unexpected caption for equity subtype ${s}`);
});
