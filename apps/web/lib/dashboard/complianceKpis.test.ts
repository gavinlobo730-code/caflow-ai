// Dashboard compliance KPI mapping tests (H13) — run with:
//   node --experimental-strip-types --test lib/dashboard/complianceKpis.test.ts
//
// The main Dashboard previously queried the legacy compliance_entries view
// directly (UTC dates, lowercase status), disagreeing with the Compliance
// workspace's counts (IST dates, canonical compliance_records via
// aggregate_dashboard). This pins that the Dashboard's KPI tiles now read
// the exact same summary fields the Compliance workspace uses.
import test from "node:test";
import assert from "node:assert/strict";
import { mapComplianceKpis } from "./complianceKpis.ts";

test("maps due_this_month and overdue from a successful response", () => {
  const kpis = mapComplianceKpis({
    success: true,
    data: { summary: { due_this_month: 7, overdue: 3 } },
    error: null,
  });
  assert.deepEqual(kpis, { filingsDueThisMonth: 7, overdueFilings: 3 });
});

test("matches the Compliance workspace's own summary numbers exactly", () => {
  // The exact shape practice/compliance/page.tsx's `s = dash?.summary` reads from.
  const workspaceSummary = { total_obligations: 40, open_obligations: 12, due_this_week: 5, due_this_month: 9, overdue: 4 };
  const kpis = mapComplianceKpis({ success: true, data: { summary: workspaceSummary }, error: null });
  assert.equal(kpis.filingsDueThisMonth, workspaceSummary.due_this_month);
  assert.equal(kpis.overdueFilings, workspaceSummary.overdue);
});

test("defaults to zero on a failed response", () => {
  const kpis = mapComplianceKpis({ success: false, data: null, error: "unauthorized" });
  assert.deepEqual(kpis, { filingsDueThisMonth: 0, overdueFilings: 0 });
});

test("defaults to zero when data/summary is missing on an otherwise-successful response", () => {
  const kpis = mapComplianceKpis({ success: true, data: null, error: null });
  assert.deepEqual(kpis, { filingsDueThisMonth: 0, overdueFilings: 0 });
});

test("defaults to zero when the response itself is null or undefined", () => {
  assert.deepEqual(mapComplianceKpis(null), { filingsDueThisMonth: 0, overdueFilings: 0 });
  assert.deepEqual(mapComplianceKpis(undefined), { filingsDueThisMonth: 0, overdueFilings: 0 });
});

test("zero overdue and zero due-this-month are preserved, not treated as missing", () => {
  const kpis = mapComplianceKpis({ success: true, data: { summary: { due_this_month: 0, overdue: 0 } }, error: null });
  assert.deepEqual(kpis, { filingsDueThisMonth: 0, overdueFilings: 0 });
});
