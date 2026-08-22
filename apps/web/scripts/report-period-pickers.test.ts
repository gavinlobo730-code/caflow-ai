// Every date-scoped report on the Accounting tab must let the user change the
// date. Run with:
//   node --experimental-strip-types --test scripts/report-period-pickers.test.ts
//
// WHY THIS EXISTS
//     The Cash Flow tab shipped without a period picker. It took the page-level
//     financial year from the header dropdown and hardcoded fyDateRange() off
//     it, so "cash flow for Q2" or for any custom range was unreachable — while
//     api.accounting.cashFlow had taken free start_date/end_date all along. The
//     control was the only missing piece, and nothing failed: the report
//     rendered correctly for the one range it could produce, so the gap was
//     invisible until a user asked why this tab looked different from the two
//     beside it.
//
//     That is the failure this file catches. A report that fetches a date range
//     and offers no way to change it is not broken in any way a test of its
//     OUTPUT would notice.
//
// WHAT IS ASSERTED
//     First that the analysis can tell the cases apart, because a ratchet whose
//     detector nobody trusts is worse than none. Then the exact set of report
//     components still lacking a picker — exact, not "no more than", so an
//     entry that stops being true has to be deleted rather than quietly kept.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "accounting", "page.tsx");

interface Report {
  name: string;
  calls: string[];
  /** The user can change the dates — a <PeriodPicker/>, or the component's own
   *  date inputs. LedgerDrillDown does the latter and is not a finding. */
  datesChangeable: boolean;
  hasPicker: boolean;
}

/**
 * Top-level components in a page module that fetch a report over dates.
 *
 * Deliberately crude: split on top-level `function Name(` and read each slice
 * as one component. The file is a single module of sibling components with no
 * nesting at column zero, so this holds — and a real parser would be a second
 * thing to keep correct for no extra truth.
 */
export function dateScopedReports(src: string): Report[] {
  const lines = src.split("\n");
  const starts: { line: number; name: string }[] = [];
  lines.forEach((l, i) => {
    const m = /^function ([A-Z]\w+)\s*\(/.exec(l);
    if (m) starts.push({ line: i, name: m[1] });
  });
  starts.push({ line: lines.length, name: "__EOF__" });

  const out: Report[] = [];
  for (let i = 0; i < starts.length - 1; i++) {
    const body = lines.slice(starts[i].line, starts[i + 1].line).join("\n");
    // The optional group catches namespaced calls — api.accounting.fxReports.realized(.
    // Without it FXReports, which is FY-locked, was invisible to this check.
    const calls = [...new Set([...body.matchAll(/api\.accounting\.(?:\w+\.)?(\w+)\(/g)].map((m) => m[1]))].sort();
    // A date-SCOPED report names one of the API's date parameters. A component
    // that merely calls an accounting endpoint is not one and must not be
    // dragged in here.
    const dated = /\b(start_date|end_date|as_of_date|as_of|period_end)\b/.test(body);
    if (calls.length && dated) {
      const hasPicker = body.includes("<PeriodPicker");
      out.push({
        name: starts[i].name,
        calls,
        hasPicker,
        // Own date inputs count. The question this file asks is whether the
        // USER can change the range, not whether one particular component was
        // used to ask them.
        datesChangeable: hasPicker || body.includes('type="date"'),
      });
    }
  }
  return out;
}

// ── The detector tells the cases apart ───────────────────────────────────────

test("a dated report with a picker is not a finding", () => {
  const found = dateScopedReports(`
function Good({ x }: P) {
  return <PeriodPicker mode={m} />;
  api.accounting.profitLoss({ start_date: s, end_date: e });
}
`);
  assert.deepEqual(found.map((r) => [r.name, r.datesChangeable]), [["Good", true]]);
});


test("a report with its own date inputs is not a finding either", () => {
  // LedgerDrillDown's real shape. It never imports PeriodPicker and does not
  // need to — it renders two <input type="date"> bound to its own state, so the
  // user can already pick any window.
  const found = dateScopedReports(`
function Drill({ x }: P) {
  api.accounting.ledger({ account_id: a, start_date: s, end_date: e });
  return <input type="date" value={startDate} onChange={setStartDate} />;
}
`);
  assert.deepEqual(found.map((r) => [r.name, r.hasPicker, r.datesChangeable]), [["Drill", false, true]]);
});


test("a namespaced report call is still seen", () => {
  // api.accounting.fxReports.realized(...) — the nested form the first draft of
  // this parser missed entirely, which hid an FY-locked report from the check.
  const found = dateScopedReports(`
function Fx({ x }: P) {
  api.accounting.fxReports.realized({ start_date: s, end_date: e });
}
`);
  assert.deepEqual(found.map((r) => [r.name, r.calls, r.datesChangeable]), [["Fx", ["realized"], false]]);
});

test("a dated report with no picker is a finding", () => {
  const found = dateScopedReports(`
function Bad({ x }: P) {
  api.accounting.cashFlow({ start_date: s, end_date: e });
}
`);
  assert.deepEqual(found.map((r) => [r.name, r.datesChangeable]), [["Bad", false]]);
});

test("an accounting call with no date parameter is not a report", () => {
  // The exact false positive that would make this ratchet unusable: a drill-down
  // scoped to an account, not to a period, has nothing to pick.
  assert.deepEqual(dateScopedReports(`
function Drill({ x }: P) {
  api.accounting.ledger({ account_id: a });
}
`), []);
});

test("components are split at top level, not merged into one blob", () => {
  const found = dateScopedReports(`
function First({ x }: P) {
  api.accounting.profitLoss({ start_date: s });
  return <PeriodPicker mode={m} />;
}

function Second({ x }: P) {
  api.accounting.trialBalance({ as_of_date: d });
}
`);
  assert.deepEqual(found.map((r) => [r.name, r.datesChangeable]), [["First", true], ["Second", false]]);
});

// ── The accounting page, as it actually stands ───────────────────────────────

/**
 * Date-scoped components the user cannot re-date, with why each is still here.
 *
 * Both remaining entries are here because they are NOT reports, and giving
 * either one a picker would make the page worse:
 *
 *   AccountingDashboard  KPI tiles for whatever the page header's FY dropdown
 *                        says. A second period control on the same screen,
 *                        disagreeing with the first, would be worse than none.
 *   FinancialReports     the export hub. It has no on-screen period — it
 *                        writes files for the selected FY. If it ever renders
 *                        a report, it belongs in the picker set instead.
 *
 * TrialBalance and FXReports were here and have been cleared. Both were the
 * same omission as Cash Flow: a report reading fyDateRange(financialYear) and
 * offering no way to change it, while the endpoint took any date all along.
 *
 * To clear an entry: let the user change the dates and DELETE its line here.
 * Do not add to this list — a new date-scoped report is re-datable.
 */
const KNOWN_UNCHANGEABLE = [
  "AccountingDashboard",
  "FinancialReports",
];

test("no new date-scoped report ships without a period picker", () => {
  const reports = dateScopedReports(fs.readFileSync(PAGE, "utf8"));

  // Vacuity guard. If the split ever stopped matching — a refactor to arrow
  // components, a move to separate files — every assertion below would pass on
  // an empty list and this file would silently protect nothing.
  assert.ok(
    reports.length >= 4,
    `only ${reports.length} date-scoped reports found on the accounting page; the parser has probably stopped matching`,
  );

  const missing = reports.filter((r) => !r.datesChangeable).map((r) => r.name).sort();
  assert.deepEqual(
    missing,
    [...KNOWN_UNCHANGEABLE].sort(),
    "a report that fetches a date range must let the user change it — " +
    "add <PeriodPicker/>, or if it is genuinely not period-scoped, say so here",
  );
});

test("the reports that were given pickers still have them", () => {
  const reports = dateScopedReports(fs.readFileSync(PAGE, "utf8"));
  for (const name of ["ProfitAndLoss", "BalanceSheet", "CashFlow", "TrialBalance", "FXReports"]) {
    const r = reports.find((x) => x.name === name);
    assert.ok(r, `${name} is no longer a recognised date-scoped report`);
    assert.ok(r.hasPicker, `${name} lost its period picker`);
  }
});
