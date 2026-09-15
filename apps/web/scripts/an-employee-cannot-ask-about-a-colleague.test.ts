/**
 * PAY-26 — the employee's own tax working, and nobody else's.
 *
 * The safety here is structural rather than checked. The endpoint takes a
 * financial year and nothing else; who the caller is comes from their own
 * Supabase identity, resolved on the server. So there is no id in this
 * component to get wrong and none for a curious employee to change in the
 * network tab.
 *
 * That property only holds while the browser side keeps its end of it: the
 * moment this file sends an employee_id or a client_id, the server has a
 * parameter it must then start defending. It has none today, and this asserts
 * that it stays that way.
 *
 * The second half is CLAUDE.md's rule, and here it has its own history:
 * `lib/services/payrollTdsEstimate.ts` was a §192 slab ladder in the browser,
 * pinned to FY 2025-26, with no old regime, no declaration and no §192(3).
 * PAY-10 deleted it. A copy rebuilt for the employee's side of the same screen
 * would be the same defect with a more vulnerable audience.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = path.join(WEB, "components/portal/TdsProjectionTab.tsx");
const PAGE = path.join(WEB, "app/portal/employee/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(TAB, "utf8");
const code = withoutComments(raw);

test("an employee cannot ask about a colleague", async (t) => {
  await t.test("sends no identifier of any kind", () => {
    for (const id of ["employee_id", "client_id", "firm_id", "employeeId", "clientId"]) {
      assert.ok(!code.includes(id),
        `${id} is sent from the browser — the server would then have to defend it`);
    }
  });

  await t.test("asks the employee endpoint, not the staff one", () => {
    // /api/payroll/tds-projection is gated by rbac() and an assignment check.
    // An employee has neither, so calling it would 403 — and reaching for it
    // is the first step towards passing an id to make it work.
    assert.match(code, /\/api\/portal\/employee\/tds-projection/);
    assert.ok(!code.includes("/api/payroll/"),
      "the staff endpoint is rbac-gated and is not this caller's door");
  });

  await t.test("computes no tax", () => {
    // Every figure is the run's own. Anything resembling a slab, a rate or a
    // rebate here is a second engine.
    for (const pattern of [/slab/i, /rebate/i, /87A/, /surcharge/i, /115BAC/, /\* *0\.\d/]) {
      assert.ok(!pattern.test(code), `${pattern} suggests tax is being computed here`);
    }
    // Not even the annual total is added up locally — the server sends it,
    // because "deducted plus the spread" is not twelve times the monthly
    // figure and the browser getting that wrong is how the old estimate did.
    assert.match(code, /data\.estimated_annual_tds_paise/);
    assert.ok(!/reduce\(/.test(code), "the browser is totalling the months itself");
  });

  await t.test("renders the server's caveats", () => {
    assert.match(code, /data\.gaps\.map/);
  });

  await t.test("a paid month and an expected one do not look the same", () => {
    // One came out of a payslip; the other is an estimate that can still move.
    assert.match(code, /m\.actual\s*\?/);
  });

  await t.test("the year list comes from the clock", () => {
    assert.match(code, /financialYearChoicesAround/);
    assert.ok(!/["']20\d\d-\d\d["']/.test(code), "a financial year is hardcoded here");
  });

  await t.test("is mounted on the employee portal", () => {
    const page = withoutComments(fs.readFileSync(PAGE, "utf8"));
    assert.match(page, /<TdsProjectionTab[\s/>]/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function TdsProjectionTab/);
  });
});
