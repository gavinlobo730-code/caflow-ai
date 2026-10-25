// A browser read of a payroll table sits behind the payroll access gate. Run with:
//   node --experimental-strip-types --test scripts/a-payroll-screen-is-withheld-from-a-person-without-payroll-access.test.ts
//
// WHY THIS EXISTS (migration 485)
//     The payroll screens read the employee, run, payslip, attendance, leave and declaration tables straight
//     from the browser. Since migration 485 the database returns those rows only to a person who holds
//     `payroll:read` and returns NOTHING, without an error, to everyone else. An empty employee list reads as
//     "this client has no employees": a statement about the world, and here a false one, because it would be a
//     statement about the person looking. So a person without payroll access is told so in words by
//     components/payroll/PayrollAccessGate, mounted as the layout of both places the staff payroll screens live.
//
// THE RULE, NOT A SPELLING
//     A file that reads one of those tables from the browser must be under a gated route, or be one of the
//     employee-portal files named in EMPLOYEE_PORTAL (none today). A new payroll screen added anywhere else fails here and names the file.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAYROLL_TABLES = [
  "payroll_employees", "payroll_runs", "payroll_slips", "attendance", "leave_balances",
  "payroll_it_declarations", "payroll_it_declaration_items",
];
const GATED_ROUTES = ["app/payroll/", "app/clients/[id]/payroll/"];
// The employee portal asks the server for its own rows too (POST-A-010), so this list is empty; it stays so a future
// employee-principal file that reads its own rows can be named here, with the reason, and not slipped under a staff gate.
const EMPLOYEE_PORTAL: string[] = [];

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name)) out.push(p);
  }
  return out;
}
const rel = (p: string) => path.relative(WEB, p).split(path.sep).join("/");
const read = (p: string) => fs.readFileSync(p, "utf8");
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const FROM = new RegExp(`\\.from\\(\\s*["'](?:${PAYROLL_TABLES.join("|")})["']`);
const READERS = [
  ...walk(path.join(WEB, "app")), ...walk(path.join(WEB, "components")), ...walk(path.join(WEB, "lib")),
].filter((p) => FROM.test(code(read(p)))).map(rel);

test("the scan finds a payroll reader when there is one, and only a payroll one", () => {
  // 7 -> 3 -> 0 on 25-10-2026 (POST-A-010): the staff screens ask the server now, and so does the employee portal, so the
  // browser reads no payroll table at all and `tests/test_a_sensitive_table_is_not_read_from_the_browser.py` makes that
  // absolute. This file keeps its rule for the day that list is ever loosened, and proves on snippets that the scan would
  // still see a reader (a scan that finds nothing would otherwise be indistinguishable from a tree with nothing to find).
  // The snippets are assembled so that no `.from("<table>")` literal sits in this file for another scanner to count as a read.
  const from = (name: string) => `.${"from"}("${name}")`;
  assert.ok(FROM.test(`const r = await sb${from("payroll_employees")}.select("id")`));
  assert.ok(FROM.test(`await supabase\n  ${from("attendance")}.select("*")`));
  assert.ok(!FROM.test(`await sb${from("clients")}.select("id")`));
  assert.deepEqual(READERS, [], `a browser file reads a payroll table: ${READERS.join(", ")}`);
});

test("every browser read of a payroll table is under a gated route or is the employee's own portal", () => {
  const ungated = READERS.filter(
    (f) => !GATED_ROUTES.some((g) => f.startsWith(g)) && !EMPLOYEE_PORTAL.some((e) => f.startsWith(e)));
  assert.deepEqual(
    ungated, [],
    "a screen reads a payroll table from the browser outside the gated routes: a person without payroll access " +
    "would see an empty list that reads as 'no employees'. Put it under app/payroll or the client payroll route, " +
    "or wrap it in PayrollAccessGate.");
});

test("both payroll route trees mount the gate as their layout", () => {
  for (const dir of GATED_ROUTES) {
    const layout = path.join(WEB, dir, "layout.tsx");
    assert.ok(fs.existsSync(layout), `${dir}layout.tsx is missing: the payroll screens under it are not gated`);
    const src = code(read(layout));
    assert.match(src, /PayrollAccessGate/, `${dir}layout.tsx does not render PayrollAccessGate`);
    assert.match(src, /\{children\}/, `${dir}layout.tsx does not pass its children through`);
  }
});

test("the gate asks payroll:read, withholds in words, and renders the page until permissions have loaded", () => {
  const src = code(read(path.join(WEB, "components/payroll/PayrollAccessGate.tsx")));
  assert.match(src, /can\(\s*"payroll"\s*,\s*"read"\s*\)/, "the gate does not ask payroll:read");
  assert.match(src, /resolved\s*&&\s*!can\(/, "the gate must act only once permissions are known (resolved)");
  assert.match(src, /You do not have access to payroll/, "the withheld state says nothing");
  assert.match(src, /not the same as there\s+being no employees/, "the withheld state must say it is not 'no employees'");
});
