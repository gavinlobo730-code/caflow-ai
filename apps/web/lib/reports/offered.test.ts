// POST-A-447. The Reports page offers a report only when the caller's permissions admit the route it reads, and each
// report's pair here is held to that route's own `rbac(...)` in the API source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { REPORT_REQUIRES, reportOffered, type ReportId } from "./offered.ts";

const WEB = join(import.meta.dirname, "..", "..");
const API = join(WEB, "..", "api");

/** The `rbac("resource", "action")` a GET route asks, read from the router's source. */
function routeRbac(routerFile: string, path: string): [string, string] {
  const src = readFileSync(join(API, "routers", routerFile), "utf8");
  const at = src.indexOf(`@router.get("${path}")`);
  assert.ok(at >= 0, `${routerFile} has no GET ${path}: the report reads a route that is gone`);
  const next = src.indexOf("@router.", at + 1);
  const body = src.slice(at, next < 0 ? undefined : next);
  const m = body.match(/rbac\("([a-z_]+)",\s*"([a-z_]+)"\)/);
  assert.ok(m, `GET ${path} in ${routerFile} asks no rbac pair`);
  return [m[1], m[2]];
}

/** What each report reads. A report that reads two routes is offered only when both admit the caller. */
const READS: Record<ReportId, Array<[string, string]>> = {
  gst_summary: [["reports.py", "/gst-summary"], ["reports.py", "/transactions"]],
  pl_statement: [["reports.py", "/transactions"]],
  compliance_status: [["compliance_ops.py", "/obligations"]],
  outstanding_invoices: [["reports.py", "/transactions"]],
};

test("each report's pair is the one its routes ask", () => {
  for (const [id, routes] of Object.entries(READS) as Array<[ReportId, Array<[string, string]>]>) {
    for (const [file, path] of routes) {
      assert.deepEqual(routeRbac(file, path), [...REPORT_REQUIRES[id]], `${id} reads GET ${path} in ${file}`);
    }
  }
});

test("the page reads what this test says it reads", () => {
  const page = readFileSync(join(WEB, "app", "reports", "page.tsx"), "utf8");
  // The data functions the page calls, and the routes behind them (lib/data/transactions.ts, lib/data/compliance.ts).
  for (const fn of ["getGSTSummary", "getTransactions", "getComplianceCalendar"]) {
    assert.ok(page.includes(`${fn}(`), `the Reports page no longer calls ${fn}: re-read what each report reads`);
  }
  const tx = readFileSync(join(WEB, "lib", "data", "transactions.ts"), "utf8");
  assert.match(tx, /api\.reports\.transactions\(/);
  assert.match(tx, /api\.reports\.gstSummary\(/);
  const comp = readFileSync(join(WEB, "lib", "data", "compliance.ts"), "utf8");
  assert.match(comp, /api\.complianceOps\.obligations\(/);
});

test("the page lists the reports through reportOffered, not the whole list", () => {
  const page = readFileSync(join(WEB, "app", "reports", "page.tsx"), "utf8");
  assert.match(page, /REPORTS\.filter\(\(r\) => reportOffered\(r\.id, can, resolved\)\)/);
  assert.doesNotMatch(page, /\{REPORTS\.map\(/, "the cards are drawn from the whole list again");
});

test("a person who may read compliance and not accounting is offered the compliance report only", () => {
  const can = (resource: string, action: string) => resource === "compliance" && action === "read";
  const offered = (Object.keys(REPORT_REQUIRES) as ReportId[]).filter((id) => reportOffered(id, can, true));
  assert.deepEqual(offered, ["compliance_status"]);
});

test("a person who may read both is offered all four", () => {
  const can = () => true;
  assert.equal((Object.keys(REPORT_REQUIRES) as ReportId[]).filter((id) => reportOffered(id, can, true)).length, 4);
});

test("nothing is withheld while the permissions are still being read", () => {
  const can = () => false;
  assert.equal((Object.keys(REPORT_REQUIRES) as ReportId[]).filter((id) => reportOffered(id, can, false)).length, 4);
});
