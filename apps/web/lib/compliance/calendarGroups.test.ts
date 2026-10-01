// practice_management-17: the calendar groups what the server sent and states no date.
//   node --experimental-strip-types --test lib/compliance/calendarGroups.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { categoryOf, groupObligations, groupsOnDay, overdueGroups, upcomingGroups } from "./calendarGroups.ts";
import type { ComplianceEntry } from "../data/compliance.ts";

const TODAY = "2026-10-10";

function entry(over: Partial<ComplianceEntry>): ComplianceEntry {
  return {
    id: "r1", client_id: "c1", compliance_type: "GSTR3B", period_start: "2026-09-01",
    period_end: "2026-09-30", due_date: "2026-10-20", filing_status: "pending",
    period_label: "GSTR-3B Sep 2026", ...over,
  };
}

test("a hundred clients' GSTR-3B on one day are ONE group that counts them", () => {
  const rows = Array.from({ length: 100 }, (_, i) =>
    entry({ id: `r${i}`, client_id: `c${i}`, filing_status: i < 30 ? "filed" : "pending" }));
  const groups = groupObligations(rows, TODAY);
  assert.equal(groups.length, 1);
  assert.deepEqual([groups[0].total, groups[0].filed, groups[0].open], [100, 30, 70]);
  assert.equal(groups[0].label, "GSTR-3B Sep 2026", "named by the engine's own label");
});

test("a group lands on the day the rows' own due date says — a QRMP quarter's 22nd stays the 22nd", () => {
  const groups = groupObligations([
    entry({ id: "monthly", due_date: "2026-10-20" }),
    entry({ id: "qrmp", client_id: "c2", due_date: "2026-10-22", period_label: "GSTR-3B Jul-Sep 2026" }),
  ], TODAY);
  assert.deepEqual(groups.map((g) => g.due_date), ["2026-10-20", "2026-10-22"]);
  assert.equal(groupsOnDay(groups, "2026-10-22")[0].label, "GSTR-3B Jul-Sep 2026");
  assert.equal(groupsOnDay(groups, "2026-10-21").length, 0, "nothing is moved to a neighbouring day");
});

test("the same obligation for different periods is not folded together", () => {
  const groups = groupObligations([
    entry({ id: "a", period_label: "GSTR-3B Sep 2026" }),
    entry({ id: "b", period_label: "GSTR-3B Aug 2026" }),
  ], TODAY);
  assert.equal(groups.length, 2);
});

test("a row sent twice — in the window and in the overdue bucket — is counted once", () => {
  const dup = entry({ id: "same", due_date: "2026-10-05" });
  const g = groupObligations([dup, { ...dup }], TODAY);
  assert.equal(g[0].total, 1);
});

test("not applicable owes nothing: it is neither filed nor still to do", () => {
  const g = groupObligations([
    entry({ id: "a", filing_status: "na" }), entry({ id: "b", filing_status: "filed" }),
    entry({ id: "c", filing_status: "pending" }),
  ], TODAY)[0];
  assert.deepEqual([g.total, g.filed, g.not_applicable, g.open], [3, 1, 1, 1]);
});

test("overdue counts the rows past due and unfiled — a filed one past due is not late", () => {
  const rows = [
    entry({ id: "late", due_date: "2026-10-05" }),
    entry({ id: "done", due_date: "2026-10-05", filing_status: "filed" }),
    entry({ id: "today", due_date: TODAY }),
  ];
  const groups = groupObligations(rows, TODAY);
  const lateGroup = groups.find((g) => g.due_date === "2026-10-05")!;
  assert.equal(lateGroup.overdue, 1);
  assert.equal(groups.find((g) => g.due_date === TODAY)!.overdue, 0, "due today is not late until the day is out");
  assert.deepEqual(overdueGroups(groups).map((g) => g.due_date), ["2026-10-05"]);
});

test("upcoming is the next groups with something still to do, from today", () => {
  const groups = groupObligations([
    entry({ id: "past", due_date: "2026-10-01" }),
    entry({ id: "filed", due_date: "2026-10-12", filing_status: "filed" }),
    entry({ id: "next", due_date: "2026-10-15", period_label: "GSTR-1 Sep 2026", compliance_type: "GSTR1" }),
    entry({ id: "later", due_date: "2026-10-20" }),
  ], TODAY);
  assert.deepEqual(upcomingGroups(groups, TODAY, 5).map((g) => g.due_date), ["2026-10-15", "2026-10-20"]);
  assert.equal(upcomingGroups(groups, TODAY, 1).length, 1, "bounded");
});

test("a form counted from a company's own AGM is a group with nothing to tick", () => {
  const g = groupObligations([], TODAY, [
    { client_id: "c9", company_name: "Acme Pvt Ltd", description: "AGM + 30 days", due_date: "2026-10-30", label: "AOC-4" },
    { client_id: "c8", company_name: "Beta Pvt Ltd", description: "AGM + 30 days", due_date: "2026-10-30", label: "AOC-4" },
  ]);
  assert.equal(g.length, 1);
  assert.deepEqual([g[0].entries.length, g[0].external.length, g[0].total, g[0].category], [0, 2, 2, "MCA"]);
});

for (const [type, category] of [
  ["GSTR1", "GST"], ["GSTR3B", "GST"], ["GSTR9", "GST"], ["PMT06", "GST"],
  ["ITR", "IncomeTax"], ["ADVANCE_TAX", "IncomeTax"], ["TAX_AUDIT", "IncomeTax"],
  ["TDS24Q", "TDS"], ["TDS26Q", "TDS"], ["TDS27Q", "TDS"], ["TCS_RETURN", "TDS"],
  ["MCA_AOC4", "MCA"], ["MCA_MGT7", "MCA"],
  ["EPF_DEPOSIT", "Payroll"], ["ESI_DEPOSIT", "Payroll"], ["TDS_SALARY_DEPOSIT", "Payroll"],
  ["SOMETHING_NEW", "Other"], ["", "Other"],
] as const) {
  test(`${JSON.stringify(type)} is coloured ${category}`, () => {
    assert.equal(categoryOf(type), category);
  });
}
